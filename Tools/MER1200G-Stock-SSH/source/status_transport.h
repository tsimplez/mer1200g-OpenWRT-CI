#ifndef MER_STATUS_TRANSPORT_H
#define MER_STATUS_TRANSPORT_H
#include <stddef.h>
#include <stdint.h>
#define MER_STATUS_PROTOCOL "mer1-stopwait-sha256-v1"
#define MER_ACK_WAIT_MS 5000u
#define MER_ACK_RETRY_MS 100u
struct mer_transport_stats {
 uint64_t events,acked,send_calls,datagrams,retransmissions,received_acks,ignored_acks,timeouts;
 uint64_t ack_latency_us_total,ack_latency_us_max;
 /* Latency upper bounds in us: 1k,5k,10k,25k,50k,100k,250k,500k,1m,5m. */
 uint64_t latency_histogram[10];
 /* Queued retransmissions per ACKed event: 0,1,2,3,4,5,6..9,10..19,20..49,50+. */
 uint64_t retry_histogram[10];
};
void mer_transport_stats_reset(void);
void mer_transport_stats_get(struct mer_transport_stats *out);
/* Fixed-address status transport. It cannot issue commands or access MTD. */
int mer_transport_open(void);
int mer_transport_validate_fd(int fd);
void mer_transport_set_tick(int (*tick)(void *),void *context);
int mer_transport_send(int fd,const void *payload,size_t bytes,const char *nonce,
                       const char *image,const char *profile,unsigned sequence);
int mer_transport_close(int fd);
#endif
