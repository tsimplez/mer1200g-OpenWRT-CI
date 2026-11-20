#define _GNU_SOURCE 1
#include "status_transport.h"
#include "sha256.h"
#include <arpa/inet.h>
#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#ifdef MER_TRANSPORT_TEST
int mer_transport_test_socket(int,int,int);
int mer_transport_test_bind(int,const struct sockaddr *,socklen_t);
int mer_transport_test_getsockname(int,struct sockaddr *,socklen_t *);
int mer_transport_test_getsockopt(int,int,int,void *,socklen_t *);
ssize_t mer_transport_test_sendto(int,const void *,size_t,int,const struct sockaddr *,socklen_t);
ssize_t mer_transport_test_recvfrom(int,void *,size_t,int,struct sockaddr *,socklen_t *);
int mer_transport_test_poll(struct pollfd *,nfds_t,int);
int mer_transport_test_clock_gettime(clockid_t,struct timespec *);
int mer_transport_test_close(int);
#define T_SOCKET mer_transport_test_socket
#define T_BIND mer_transport_test_bind
#define T_GETSOCKNAME mer_transport_test_getsockname
#define T_GETSOCKOPT mer_transport_test_getsockopt
#define T_SENDTO mer_transport_test_sendto
#define T_RECVFROM mer_transport_test_recvfrom
#define T_POLL mer_transport_test_poll
#define T_CLOCK mer_transport_test_clock_gettime
#define T_CLOSE mer_transport_test_close
#else
#define T_SOCKET socket
#define T_BIND bind
#define T_GETSOCKNAME getsockname
#define T_GETSOCKOPT getsockopt
#define T_SENDTO sendto
#define T_RECVFROM recvfrom
#define T_POLL poll
#define T_CLOCK clock_gettime
#define T_CLOSE close
#endif

static int (*wait_tick)(void *);
static void *wait_context;
static struct mer_transport_stats stats;
void mer_transport_stats_reset(void){memset(&stats,0,sizeof(stats));}
void mer_transport_stats_get(struct mer_transport_stats *out){if(out)*out=stats;}
static int bad(int error){errno=error;return -1;}
static int timed_out(void){stats.timeouts++;return bad(ETIMEDOUT);}
static int now_us(uint64_t *value){
 struct timespec now;
 if(T_CLOCK(CLOCK_MONOTONIC,&now))return -1;
 if(now.tv_sec<0 || now.tv_nsec<0 || now.tv_nsec>=1000000000L)return bad(EINVAL);
 *value=(uint64_t)now.tv_sec*1000000u+(unsigned long)now.tv_nsec/1000u;return 0;
}
static void acknowledged(uint64_t latency,unsigned queued){
 static const uint64_t bounds[]={1000,5000,10000,25000,50000,100000,250000,500000,1000000,5000000};
 stats.acked++;stats.ack_latency_us_total+=latency;
 if(latency>stats.ack_latency_us_max)stats.ack_latency_us_max=latency;
 unsigned bucket=0;while(bucket<9 && latency>=bounds[bucket])bucket++;
 stats.latency_histogram[bucket]++;
 unsigned retries=queued?queued-1:0;
 bucket=retries<=5?retries:retries<10?6:retries<20?7:retries<50?8:9;
 stats.retry_histogram[bucket]++;
}
static int hex_string(const char *p,size_t bytes){
 if(!p || strlen(p)!=bytes)return 0;
 for(size_t i=0;i<bytes;i++)if(!((p[i]>='0' && p[i]<='9') || (p[i]>='a' && p[i]<='f')))return 0;
 return 1;
}
static int profile_string(const char *p){
 if(!p)return 0;
 size_t n=strlen(p);if(!n || n>64)return 0;
 for(size_t i=0;i<n;i++)if(!((p[i]>='a' && p[i]<='z') || (p[i]>='0' && p[i]<='9') || p[i]=='-'))return 0;
 return 1;
}
void mer_transport_set_tick(int (*tick)(void *),void *context){wait_tick=tick;wait_context=context;}
int mer_transport_open(void){
 int fd=T_SOCKET(AF_INET,SOCK_DGRAM|SOCK_NONBLOCK|SOCK_CLOEXEC,0);if(fd<0)return -1;
 struct sockaddr_in source;memset(&source,0,sizeof(source));source.sin_family=AF_INET;
 source.sin_addr.s_addr=htonl(0xc0a80232u);
 if(T_BIND(fd,(const struct sockaddr *)&source,sizeof(source))){int error=errno;T_CLOSE(fd);return bad(error);}
 return fd;
}
int mer_transport_validate_fd(int fd){
 int type=0;socklen_t size=sizeof(type);struct sockaddr_in local;memset(&local,0,sizeof(local));
 if(fd<3 || T_GETSOCKOPT(fd,SOL_SOCKET,SO_TYPE,&type,&size) || size!=sizeof(type) || type!=SOCK_DGRAM)return bad(EINVAL);
 size=sizeof(local);
 if(T_GETSOCKNAME(fd,(struct sockaddr *)&local,&size) || size!=sizeof(local) || local.sin_family!=AF_INET ||
    local.sin_addr.s_addr!=htonl(0xc0a80232u) || !local.sin_port)return bad(EINVAL);
 return 0;
}
int mer_transport_close(int fd){return T_CLOSE(fd);}
int mer_transport_send(int fd,const void *payload,size_t bytes,const char *nonce,
                       const char *image,const char *profile,unsigned sequence){
 if(fd<3 || !payload || !bytes || bytes>1400 || !sequence || !hex_string(nonce,32) ||
    !hex_string(image,64) || !profile_string(profile))return bad(EINVAL);
 char hash[65],expected[384],received[512];mer_sha256(payload,bytes,hash);
 int expected_bytes=snprintf(expected,sizeof(expected),
  "MERACK1 nonce=%s image=%s profile=%s seq=%u payload_sha256=%s\n",nonce,image,profile,sequence,hash);
 if(expected_bytes<1 || (size_t)expected_bytes>=sizeof(expected))return bad(EOVERFLOW);
 struct sockaddr_in destination;memset(&destination,0,sizeof(destination));destination.sin_family=AF_INET;
 destination.sin_addr.s_addr=htonl(0xc0a80294u);destination.sin_port=htons(39001);
 uint64_t start,now,next_send;unsigned interrupts=0,queued=0;
 if(now_us(&start))return -1;
 stats.events++;
 next_send=start;
 for(;;){
  if(wait_tick && wait_tick(wait_context))return -1;
  if(now_us(&now))return -1;
  if(now<start || now-start>=(uint64_t)MER_ACK_WAIT_MS*1000u)return timed_out();
  if(now>=next_send){
   stats.send_calls++;
   ssize_t sent=T_SENDTO(fd,payload,bytes,MSG_DONTWAIT|MSG_NOSIGNAL,
                        (const struct sockaddr *)&destination,sizeof(destination));
   if(sent==(ssize_t)bytes){stats.datagrams++;if(queued++)stats.retransmissions++;interrupts=0;next_send=now+(uint64_t)MER_ACK_RETRY_MS*1000u;}
   else if(sent<0 && errno==EINTR && ++interrupts<=32)continue;
   else if(sent<0 && (errno==EAGAIN || errno==EWOULDBLOCK || errno==ENOBUFS)){next_send=now+(uint64_t)MER_ACK_RETRY_MS*1000u;}
   else return sent>=0?bad(EIO):-1;
  }
  /* Drain only bounded batches so invalid/spoofed ACKs cannot starve deadlines. */
  for(unsigned batch=0;batch<32;batch++){
   struct sockaddr_in peer;memset(&peer,0,sizeof(peer));socklen_t peer_size=sizeof(peer);
   ssize_t got=T_RECVFROM(fd,received,sizeof(received),MSG_DONTWAIT,(struct sockaddr *)&peer,&peer_size);
   if(got<0){if(errno==EAGAIN || errno==EWOULDBLOCK)break;if(errno==EINTR)continue;return -1;}
   stats.received_acks++;
   if(peer_size==sizeof(peer) && peer.sin_family==AF_INET && peer.sin_addr.s_addr==destination.sin_addr.s_addr &&
      peer.sin_port==destination.sin_port && got==expected_bytes && !memcmp(received,expected,(size_t)got)){
    if(wait_tick && wait_tick(wait_context))return -1;
    if(now_us(&now))return -1;
    if(now<start || now-start>=(uint64_t)MER_ACK_WAIT_MS*1000u)return timed_out();
    acknowledged(now-start,queued);
    return 0;
   }
   stats.ignored_acks++;
  }
  if(now_us(&now))return -1;
  if(now<start || now-start>=(uint64_t)MER_ACK_WAIT_MS*1000u)return timed_out();
  uint64_t delay=next_send>now?next_send-now:0,remaining=(uint64_t)MER_ACK_WAIT_MS*1000u-(now-start);
  if(delay>100000)delay=100000;
  if(delay>remaining)delay=remaining;
  struct pollfd p={.fd=fd,.events=POLLIN,.revents=0};
  int result=T_POLL(&p,1,(int)((delay+999u)/1000u));
  if(result<0 && errno!=EINTR)return -1;
  if(result>0 && (p.revents&(POLLERR|POLLHUP|POLLNVAL)))return bad(EIO);
 }
}
