#define _GNU_SOURCE 1
#include "status_transport.h"
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#define PROBE_NONCE "8d1a530eca234fb48b09f8c7580a451d"
#define PROBE_IMAGE "2d735c31e87c592218114602b0217c651c60a7c49d2323760f342e63b7a13e69"
#define PROBE_PROFILE "mer1200g-ack-readonly-probe"
/* Intentionally linked only to status_transport.c and sha256.c. No flash API. */
static uint64_t monotonic_us(void){
 struct timespec now;if(clock_gettime(CLOCK_MONOTONIC,&now))return 0;
 return (uint64_t)now.tv_sec*1000000u+(unsigned long)now.tv_nsec/1000u;
}
static void report(unsigned total,unsigned completed,uint64_t elapsed,int error){
 struct mer_transport_stats s;mer_transport_stats_get(&s);
 printf("MERPROBE-RESULT protocol=%s total=%u completed=%u error=%d elapsed_us=%" PRIu64
        " events=%" PRIu64 " acked=%" PRIu64 " send_calls=%" PRIu64 " datagrams=%" PRIu64
        " retransmissions=%" PRIu64 " received_acks=%" PRIu64 " ignored_acks=%" PRIu64
        " timeouts=%" PRIu64 " latency_us_total=%" PRIu64 " latency_us_max=%" PRIu64 "\n",
        MER_STATUS_PROTOCOL,total,completed,error,elapsed,s.events,s.acked,s.send_calls,s.datagrams,
        s.retransmissions,s.received_acks,s.ignored_acks,s.timeouts,s.ack_latency_us_total,s.ack_latency_us_max);
 printf("MERPROBE-LATENCY upper_us=1000,5000,10000,25000,50000,100000,250000,500000,1000000,5000000 counts=");
 for(unsigned i=0;i<10;i++)printf("%s%" PRIu64,i?",":"",s.latency_histogram[i]);
 printf("\nMERPROBE-RETRIES buckets=0,1,2,3,4,5,6-9,10-19,20-49,50+ counts=");
 for(unsigned i=0;i<10;i++)printf("%s%" PRIu64,i?",":"",s.retry_histogram[i]);
 putchar('\n');fflush(stdout);
}
int main(int argc,char **argv){
 unsigned total=100000;
 if(argc==3 && !strcmp(argv[1],"--events")){
  char *end=NULL;errno=0;unsigned long n=strtoul(argv[2],&end,10);
  if(errno || !end || *end || n<1 || n>110000 || argv[2][0]<'1' || argv[2][0]>'9')return 64;
  total=(unsigned)n;
 }else if(argc!=1){fprintf(stderr,"usage: %s [--events 1..110000]\n",argv[0]);return 64;}
 char padding[769];memset(padding,'x',768);padding[768]=0;
 int fd=mer_transport_open();if(fd<0){perror("probe bind");return 1;}
 if(mer_transport_validate_fd(fd)){perror("probe socket");mer_transport_close(fd);return 1;}
 mer_transport_stats_reset();uint64_t start=monotonic_us();unsigned completed=0;int error=0;
 for(unsigned seq=1;seq<=total;seq++){
  char packet[1400];int n=snprintf(packet,sizeof(packet),
   "MERPROBE1 proto=%s nonce=%s image=%s profile=%s seq=%u total=%u data=%s\n",
   MER_STATUS_PROTOCOL,PROBE_NONCE,PROBE_IMAGE,PROBE_PROFILE,seq,total,padding);
  if(n<0 || (size_t)n>=sizeof(packet)){error=EOVERFLOW;break;}
  if(mer_transport_send(fd,packet,(size_t)n,PROBE_NONCE,PROBE_IMAGE,PROBE_PROFILE,seq)){error=errno?errno:EIO;break;}
  completed=seq;
  if(seq%10000==0 && seq!=total){printf("MERPROBE-PROGRESS completed=%u total=%u elapsed_us=%" PRIu64 "\n",seq,total,monotonic_us()-start);fflush(stdout);}
 }
 report(total,completed,monotonic_us()-start,error);mer_transport_close(fd);
 return error?1:0;
}
