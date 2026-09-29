// availability_gate -- the host-side availability gate of the phase-8
// takeover demo (phase8-W16; replaces tools/timeline/scenario.py's rclpy gate).
//
// Autoware is launched with
//   operation_mode_availability_topic:=/system/operation_mode/availability_raw
// and this node republishes the LATEST raw sample on
// /system/operation_mode/availability (the topic the island's mrm_handler
// guards) with `autonomous &= !odd_exit`, same type and QoS (depth 1,
// reliable, volatile), at 10 Hz from its own timer, while that sample is
// younger than raw_max_age_ms (1000); once it is older, nothing: a stalled or
// dead converter still stops the stream, 1 s later. The timer, not the raw
// sample, sets the island's cadence: Autoware's converter leaves gaps of 400
// to 700 ms on a loaded host (docs/takeover-trace.md, b1) and a 10 Hz timer
// hides every one of them under the island's 500 ms timeout.
//
// Why C++ and why this shape (docs/takeover-trace.md, "The gate stall"):
// the rclpy gate stalled 250-1134 ms on a loaded host because its one
// executor thread rewrote a file every tick (the sample count) and wrote its
// JSONL events inline; under heavy writeback, ext4 blocked the truncating
// close() (rq_qos_wait, folio_wait_bit_common) and took the timer and the raw
// subscription down with it. Here the executor thread makes no file system
// call after start-up:
//   - events and console lines go through a queue to a writer thread; a
//     writer blocked in the kernel delays a log line, never a sample;
//   - the sample count the hpc-loss button reads is a 64-byte text record in
//     a MAP_SHARED page on /dev/shm (tmpfs: no writeback), updated with a
//     memcpy;
//   - mlockall() after start-up keeps the process's code resident, so a
//     reclaim-heavy host cannot turn a callback into a major page fault.
// It runs under SCHED_FIFO when the rtprio limit allows it (gate-rt, beside
// this binary); the stall measured was I/O, not the CPU run queue, so FIFO
// is a margin, not the fix.
//
// Control interface (as the rclpy gate's; tools/timeline/scenario.py):
//   SIGUSR1 / SIGUSR2   ODD exit / ODD enter
//   /demo/odd/exit      std_msgs/Bool, the same flag (W3's odd_monitor)
//   SIGSTOP / SIGCONT   HPC loss / restore: every thread stops, the stream is
//                       truly silent; the island alone detects it
// The pid file (--pid-file) holds "<pid> <count file>"; the count file holds
// "<samples published> <CLOCK_MONOTONIC ns of the last publish>".
//
// Events (--log, JSON Lines, tools/timeline/tlcommon.py's schema, source
// "gate"): `odd` on each flag change; `publish` for the first sample with a
// new `autonomous`; `stall` when the timer (`tick`) or the raw stream
// (`availability_raw`) was more than stall_ms late; `stale` when the raw
// sample ages out or comes back; `stats` at exit (the largest publish gap).
//
// Usage: availability_gate [--log F] [--pid-file F] [--no-mlock]
//                          [--ros-args -p period_ms:=100 -p raw_max_age_ms:=1000
//                           -p stall_ms:=250 -p odd_timeout_s:=0.0]
// odd_timeout_s > 0 (W3's availability_gate): the ODD is treated as left
// while /demo/odd/exit has been silent that long, or never heard.

#include <fcntl.h>
#include <sched.h>
#include <signal.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include <atomic>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/bool.hpp>
#include <tier4_system_msgs/msg/operation_mode_availability.hpp>

namespace
{
using Avail = tier4_system_msgs::msg::OperationModeAvailability;
constexpr const char * RAW = "/system/operation_mode/availability_raw";
constexpr const char * AVAIL = "/system/operation_mode/availability";

int64_t mono_ns()
{
  timespec ts{};
  clock_gettime(CLOCK_MONOTONIC, &ts);  // == Python's time.monotonic_ns()
  return int64_t(ts.tv_sec) * 1000000000LL + ts.tv_nsec;
}

// Set from signal handlers (any thread), consumed on the executor thread.
std::atomic<int> g_odd_request{0};  // 0 none, 1 exit (SIGUSR1), 2 enter (SIGUSR2)
std::atomic<int> g_resumed{0};      // SIGCONT seen: the next gap is the hpc-loss act, not a stall

extern "C" void on_usr1(int) { g_odd_request.store(1); }
extern "C" void on_usr2(int) { g_odd_request.store(2); }
extern "C" void on_cont(int) { g_resumed.store(1); }

std::string fmt_ms(int64_t ns)
{
  char b[48];
  std::snprintf(b, sizeof b, "%.3f", double(ns) / 1e6);
  return b;
}

// Log lines leave the executor thread through this queue. push() takes the
// mutex only to append; the writer holds it only to swap the batch out, and
// does its I/O outside it.
class AsyncWriter
{
public:
  explicit AsyncWriter(const std::string & path)
  {
    if (!path.empty()) {
      mkdirs(path);
      file_ = std::fopen(path.c_str(), "a");
      if (!file_) {
        std::fprintf(stderr, "gate: cannot open %s: %s\n", path.c_str(), std::strerror(errno));
      }
    }
    thread_ = std::thread([this] { run(); });
  }
  ~AsyncWriter() { stop(); }

  // One tlcommon event; `extra` is appended as further top-level members.
  void event(
    int64_t t, const char * kind, const char * hazard, const char * marker, const std::string & value,
    const std::string & extra = "")
  {
    std::string s = "{\"t_mono_ns\": " + std::to_string(t) + ", \"source\": \"gate\", \"kind\": \"" +
      kind + "\", \"hazard\": " + quote(hazard) + ", \"rung\": null, \"marker\": " + quote(marker) +
      ", \"value\": " + value + (extra.empty() ? "" : ", " + extra) + "}\n";
    push(true, std::move(s));
  }
  void say(const std::string & line) { push(false, "gate: " + line + "\n"); }

  void stop()
  {
    {
      std::lock_guard<std::mutex> l(m_);
      if (stop_) {return;}
      stop_ = true;
    }
    cv_.notify_one();
    if (thread_.joinable()) {thread_.join();}
    if (file_) {std::fclose(file_); file_ = nullptr;}
  }

private:
  struct Item
  {
    bool to_file;
    std::string s;
  };

  static std::string quote(const char * s) { return s ? std::string("\"") + s + "\"" : "null"; }

  static void mkdirs(const std::string & file)
  {
    for (size_t i = 1; i < file.size(); ++i) {
      if (file[i] == '/') {::mkdir(file.substr(0, i).c_str(), 0755);}
    }
  }

  void push(bool to_file, std::string s)
  {
    {
      std::lock_guard<std::mutex> l(m_);
      q_.push_back(Item{to_file, std::move(s)});
    }
    cv_.notify_one();
  }

  void run()
  {
    std::vector<Item> batch;
    for (;;) {
      {
        std::unique_lock<std::mutex> l(m_);
        cv_.wait(l, [this] { return stop_ || !q_.empty(); });
        batch.swap(q_);
        if (batch.empty() && stop_) {return;}
      }
      bool f = false, o = false;
      for (auto & i : batch) {
        if (i.to_file) {
          if (file_) {std::fputs(i.s.c_str(), file_); f = true;}
        } else {
          std::fputs(i.s.c_str(), stdout);
          o = true;
        }
      }
      if (f) {std::fflush(file_);}
      if (o) {std::fflush(stdout);}
      batch.clear();
    }
  }

  std::FILE * file_{nullptr};
  std::mutex m_;
  std::condition_variable cv_;
  std::vector<Item> q_;
  bool stop_{false};
  std::thread thread_;
};

// "<n> <t_ns>" in a shared page on tmpfs: the hpc-loss button reads the last
// sample before its SIGSTOP from here. Updating it is a memcpy, no syscall.
class CountRecord
{
public:
  static constexpr size_t SIZE = 64;

  bool open(const std::string & path)
  {
    int fd = ::open(path.c_str(), O_RDWR | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (fd < 0) {return false;}
    if (::ftruncate(fd, SIZE) != 0) {::close(fd); return false;}
    void * p = ::mmap(nullptr, SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    ::close(fd);
    if (p == MAP_FAILED) {return false;}
    p_ = static_cast<char *>(p);
    path_ = path;
    update(0, 0);
    return true;
  }
  void update(uint64_t n, int64_t t)
  {
    if (!p_) {return;}
    char b[SIZE];
    std::memset(b, ' ', SIZE);
    int k = std::snprintf(b, SIZE - 1, "%llu %lld", (unsigned long long)n, (long long)t);
    if (k >= 0 && size_t(k) < SIZE - 1) {b[k] = ' ';}
    b[SIZE - 1] = '\n';
    std::memcpy(p_, b, SIZE);
  }
  const std::string & path() const { return path_; }
  void remove()
  {
    if (p_) {::munmap(p_, SIZE); p_ = nullptr;}
    if (!path_.empty()) {::unlink(path_.c_str());}
  }

private:
  char * p_{nullptr};
  std::string path_;
};

class Gate : public rclcpp::Node
{
public:
  Gate(AsyncWriter & w, CountRecord & count)
  : rclcpp::Node("availability_gate"), w_(w), count_(count)
  {
    period_ns_ = declare_parameter<int64_t>("period_ms", 100) * 1000000LL;
    raw_max_age_ns_ = declare_parameter<int64_t>("raw_max_age_ms", 1000) * 1000000LL;
    stall_ns_ = declare_parameter<int64_t>("stall_ms", 250) * 1000000LL;
    gap_report_ns_ = declare_parameter<int64_t>("gap_report_ms", 150) * 1000000LL;
    odd_timeout_ns_ = int64_t(declare_parameter<double>("odd_timeout_s", 0.0) * 1e9);

    auto qos = rclcpp::QoS(rclcpp::KeepLast(1)).reliable().durability_volatile();
    pub_ = create_publisher<Avail>(AVAIL, qos);
    raw_sub_ = create_subscription<Avail>(
      RAW, qos, [this](Avail::ConstSharedPtr m) { on_raw(*m); });
    odd_sub_ = create_subscription<std_msgs::msg::Bool>(
      "/demo/odd/exit", qos, [this](std_msgs::msg::Bool::ConstSharedPtr m) {
        odd_topic_t_ = mono_ns();
        set_odd(m->data, "/demo/odd/exit", odd_topic_t_);
      });
    timer_ = create_wall_timer(std::chrono::nanoseconds(period_ns_), [this] { on_tick(); });
  }

  void report_stats()
  {
    std::string v = "{\"n\": " + std::to_string(n_) + ", \"max_publish_gap_ms\": " +
      fmt_ms(max_pub_gap_) + ", \"publish_gaps_over_ms\": " + fmt_ms(gap_report_ns_) +
      ", \"publish_gaps_over\": " + std::to_string(gaps_over_) + ", \"max_tick_gap_ms\": " +
      fmt_ms(max_tick_gap_) + ", \"max_raw_gap_ms\": " + fmt_ms(max_raw_gap_) +
      ", \"resumes\": " + std::to_string(resumes_) + "}";
    w_.event(mono_ns(), "stats", nullptr, "availability", v);
    w_.say(
      "stats: " + std::to_string(n_) + " samples, largest publish gap " + fmt_ms(max_pub_gap_) +
      " ms, " + std::to_string(gaps_over_) + " gaps over " + fmt_ms(gap_report_ns_) +
      " ms, largest tick gap " + fmt_ms(max_tick_gap_) + " ms, largest raw gap " +
      fmt_ms(max_raw_gap_) + " ms (SIGCONT resumes excluded: " + std::to_string(resumes_) + ")");
  }

private:
  void set_odd(bool v, const char * how, int64_t t)
  {
    if (odd_exit_ == v) {return;}
    odd_exit_ = v;
    w_.event(t, "odd", "odd_exit", nullptr, v ? "true" : "false",
      std::string("\"how\": \"") + how + "\"");
    w_.say(std::string("odd_exit -> ") + (v ? "true" : "false") + " (" + how + ")");
  }

  void on_raw(const Avail & raw)
  {
    const int64_t t = mono_ns();
    if (raw_t_ != 0) {
      const int64_t gap = t - raw_t_;
      if (!resume_pending_raw_) {
        if (gap > max_raw_gap_) {max_raw_gap_ = gap;}
        if (gap > stall_ns_) {
          // Autoware's converter (or the path to us) was late
          w_.event(t, "stall", nullptr, "availability_raw", "{\"gap_ms\": " + fmt_ms(gap) + "}");
        }
      }
    }
    resume_pending_raw_ = false;
    raw_ = raw;
    raw_t_ = t;
  }

  void on_tick()
  {
    const int64_t t = mono_ns();
    // A SIGCONT means the gap that ends here was the hpc-loss act: not a stall.
    const bool resumed = g_resumed.exchange(0) != 0;
    if (resumed) {
      ++resumes_;
      resume_pending_raw_ = true;
      last_pub_t_ = 0;
      w_.event(t, "resume", "hpc_loss", nullptr, "{}");
      w_.say("SIGCONT: resumed");
    }
    switch (g_odd_request.exchange(0)) {
      case 1: set_odd(true, "SIGUSR1", t); break;
      case 2: set_odd(false, "SIGUSR2", t); break;
      default: break;
    }
    if (tick_t_ != 0 && !resumed) {
      const int64_t gap = t - tick_t_;
      if (gap > max_tick_gap_) {max_tick_gap_ = gap;}
      if (gap > stall_ns_) {
        // the gate itself was late (its timer did not run)
        w_.event(t, "stall", nullptr, "tick", "{\"gap_ms\": " + fmt_ms(gap) + "}");
      }
    }
    tick_t_ = t;

    const bool fresh = raw_t_ != 0 && t - raw_t_ <= raw_max_age_ns_;
    if (fresh != fresh_) {
      fresh_ = fresh;
      w_.event(t, "stale", nullptr, "availability_raw",
        std::string("{\"fresh\": ") + (fresh ? "true" : "false") + "}");
      w_.say(fresh ? "availability_raw fresh: publishing" :
        "availability_raw older than raw_max_age_ms: silent");
    }
    if (!fresh) {return;}

    bool blocked = odd_exit_;
    if (odd_timeout_ns_ > 0 && (odd_topic_t_ == 0 || t - odd_topic_t_ > odd_timeout_ns_)) {
      blocked = true;  // the ODD monitor is silent: treat the ODD as left (W3)
    }
    Avail out = raw_;
    out.autonomous = raw_.autonomous && !blocked;
    pub_->publish(out);
    const int64_t tp = mono_ns();
    ++n_;
    count_.update(n_, tp);
    if (last_pub_t_ != 0) {
      const int64_t gap = tp - last_pub_t_;
      if (gap > max_pub_gap_) {max_pub_gap_ = gap;}
      if (gap > gap_report_ns_) {++gaps_over_;}
    }
    last_pub_t_ = tp;
    if (!have_last_ || out.autonomous != last_auto_) {
      w_.event(tp, "publish", "odd_exit", "availability",
        std::string("{\"autonomous\": ") + (out.autonomous ? "true" : "false") +
        ", \"raw_autonomous\": " + (raw_.autonomous ? "true" : "false") +
        ", \"n\": " + std::to_string(n_) + "}");
      w_.say(std::string("availability.autonomous -> ") + (out.autonomous ? "true" : "false") +
        " (sample " + std::to_string(n_) + ")");
      have_last_ = true;
      last_auto_ = out.autonomous;
    }
  }

  AsyncWriter & w_;
  CountRecord & count_;
  rclcpp::Publisher<Avail>::SharedPtr pub_;
  rclcpp::Subscription<Avail>::SharedPtr raw_sub_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr odd_sub_;
  rclcpp::TimerBase::SharedPtr timer_;

  int64_t period_ns_{}, raw_max_age_ns_{}, stall_ns_{}, gap_report_ns_{}, odd_timeout_ns_{};
  Avail raw_;
  int64_t raw_t_{0}, tick_t_{0}, last_pub_t_{0}, odd_topic_t_{0};
  bool odd_exit_{false}, fresh_{false}, have_last_{false}, last_auto_{false};
  bool resume_pending_raw_{false};
  uint64_t n_{0}, gaps_over_{0}, resumes_{0};
  int64_t max_pub_gap_{0}, max_tick_gap_{0}, max_raw_gap_{0};
};

std::string sched_desc()
{
  const int pol = sched_getscheduler(0);
  sched_param sp{};
  sched_getparam(0, &sp);
  const char * name = pol == SCHED_FIFO ? "SCHED_FIFO" : pol == SCHED_RR ? "SCHED_RR" : "SCHED_OTHER";
  return std::string(name) + " " + std::to_string(sp.sched_priority);
}

void install(int sig, void (*fn)(int))
{
  struct sigaction sa{};
  sa.sa_handler = fn;
  sigemptyset(&sa.sa_mask);
  sa.sa_flags = SA_RESTART;
  sigaction(sig, &sa, nullptr);
}
}  // namespace

int main(int argc, char ** argv)
{
  // Signals first: a SIGUSR1 during start-up must not kill the gate.
  install(SIGUSR1, on_usr1);
  install(SIGUSR2, on_usr2);
  install(SIGCONT, on_cont);

  auto args = rclcpp::init_and_remove_ros_arguments(argc, argv);
  std::string log, pid_file;
  bool lock = true;
  for (size_t i = 1; i < args.size(); ++i) {
    if (args[i] == "--log" && i + 1 < args.size()) {
      log = args[++i];
    } else if (args[i] == "--pid-file" && i + 1 < args.size()) {
      pid_file = args[++i];
    } else if (args[i] == "--no-mlock") {
      lock = false;
    } else {
      std::fprintf(stderr, "availability_gate: unknown argument %s\n", args[i].c_str());
      return 2;
    }
  }

  AsyncWriter w(log);
  CountRecord count;
  const std::string shm = "/dev/shm/sai-availability-gate-" + std::to_string(getpid()) + ".count";
  if (!count.open(shm) && !(pid_file.size() && count.open(pid_file + ".count"))) {
    std::fprintf(stderr, "gate: no count record (%s): %s\n", shm.c_str(), std::strerror(errno));
  }
  if (!pid_file.empty()) {
    // start-up only: the executor thread does no file I/O once it spins
    std::string dir = pid_file.substr(0, pid_file.rfind('/'));
    if (!dir.empty() && dir != pid_file) {::mkdir(dir.c_str(), 0755);}
    if (std::FILE * f = std::fopen(pid_file.c_str(), "w")) {
      std::fprintf(f, "%d %s\n", int(getpid()), count.path().c_str());
      std::fclose(f);
    }
  }

  auto node = std::make_shared<Gate>(w, count);

  std::string mlock_desc = "off";
  if (lock) {
    if (mlockall(MCL_CURRENT | MCL_FUTURE) == 0) {
      mlock_desc = "MCL_CURRENT|MCL_FUTURE";
    } else if (mlockall(MCL_CURRENT) == 0) {
      mlock_desc = "MCL_CURRENT";
    } else {
      mlock_desc = std::string("failed: ") + std::strerror(errno);
    }
  }
  w.say(std::string(RAW) + " -> " + AVAIL + " (pid " + std::to_string(getpid()) + "), log " +
    (log.empty() ? "-" : log) + ", " + sched_desc() + ", mlockall " + mlock_desc + ", count " +
    count.path());

  rclcpp::executors::SingleThreadedExecutor exec;
  exec.add_node(node);
  exec.spin();

  node->report_stats();
  w.stop();
  count.remove();
  rclcpp::shutdown();
  return 0;
}
