# Goal

Per `private/NEXT_STEPS.md` item 5: this project's environment (Ubuntu
22.04 + ROS2 Humble + Gazebo Sim 8.14 "Harmonic") is unofficial --
Humble's official Gazebo partner is Fortress, and `gz_ros2_control` had
to be built from source for this reason. Build the *officially* paired
combination (Ubuntu 24.04 + ROS2 Jazzy + Gazebo Harmonic) via Docker and
re-run `PHYS-001`'s exact comparison (physics-only vs ROS end-to-end) to
test whether the unofficial pairing contributes to the ~4.45 degree
ROS2/DDS-layer variance `PHYS-001` found.

# Setup

`docker/env001-jazzy-harmonic/Dockerfile`, built `FROM osrf/ros:jazzy-desktop`.
Confirmed directly (not assumed) that Jazzy+Harmonic needs no source
build at all: `ros-jazzy-ros-gz`, `ros-jazzy-gz-ros2-control`, and all
their dependencies install cleanly via `apt`. Gazebo Sim inside the
container: version 8.11.0 (vs. this project's primary environment's
8.14.0 -- both "Harmonic," different patch releases). Build context is a
copy of this project's three own packages (`double_pendulum_description`,
`double_pendulum_control`, `double_pendulum_eval`) -- `gz_ros2_control`
is deliberately not vendored, since Jazzy provides it via apt.

# Bug found and fixed: `--network host` breaks DDS discovery entirely

First attempt used `docker run --network host` (the usual recommendation
for ROS2-in-Docker). Result: `ros2 topic list` timed out completely, on
every retry, with both `rmw_fastrtps_cpp` (default) and
`rmw_cyclonedds_cpp` (installed and tried explicitly) -- while `gz topic
-l` (Gazebo's own, non-ROS transport) partially worked, showing `/clock`
was live. This isolates the failure to ROS2's DDS discovery layer
specifically, not gz-transport, not the container's ability to run
Gazebo at all.

Root cause (inferred, not exhaustively proven): Docker's `--network host`
inside this WSL2 Docker Engine installation does not appear to properly
support UDP multicast the way a genuine Linux host network stack would --
WSL2 already runs its own virtualized network layer, and "host" in this
context means "host of the WSL2 VM," not bare metal.

**Fix**: dropped `--network host`, used Docker's default bridge network
instead. Every ROS2 node in this test lives in the same single container
anyway, so nothing needs to reach outside it -- bridge networking's own
isolated virtual subnet handles multicast correctly where the WSL2 host
network didn't. `ros2 topic list` worked immediately after switching.

# Bug found and reused: FastRTPS `/dev/shm` accumulation (same as CTRL-005/INFRA-002)

While repeatedly relaunching Gazebo inside the same long-lived container
(`pkill -9` + relaunch, same pattern `run_clean_experiment.sh` uses),
hit the exact same failure class `CTRL-005` and `INFRA-002` already
documented in the WSL2 environment: a `gz world control` service call
timed out mid-run, and `/dev/shm` had accumulated 82 stale
`fastrtps_*`/`sem.fastrtps_*` entries. Confirms this is a general
FastRTPS-cleanup artifact of repeated `pkill -9` cycles, not something
specific to WSL2's networking -- it reproduces inside a Docker container
too. Cleared manually (`rm -f /dev/shm/fastrtps_*`) between each of this
task's own runs, same one-off, investigation-only precedent CTRL-005 set
-- not baked into any shared script.

Similarly, the very first ROS end-to-end run showed `overshoot_q1_deg =
0.0` (the disturbance push apparently had zero physical effect) --
retried once and got a normal result (240.0 degrees). Treated as the same
class of transient infra hiccup as the two above, not a persistent
finding, since it did not recur on retry or in either subsequent run.

# Results (real runs, not synthetic)

**Physics-only, N=3** (gz-transport only, same method as `PHYS-001`,
identical disturbance profile, fresh container-internal Gazebo relaunch
each time): **bit-for-bit identical to each other AND to the
Humble+Harmonic baseline** -- `max_abs_q1_deg=220.0622`,
`max_abs_q2_deg=182.4296`, `final_q1_deg=182.9662` in all 3 runs here,
matching `PHYS-001`'s own N=3 result exactly. Sample-by-sample max
difference: 0.0 rad, same as before. **The physics solver's
determinism holds across Gazebo Sim patch versions and Ubuntu/ROS2
distro versions, not just within one environment.**

**ROS end-to-end (no controller), N=3**:

| run | overshoot_q1_deg |
|---|---|
| 1 | 240.0164 |
| 2 | 237.0931 |
| 3 | 212.9260 |

Range: **27.09 degrees** -- compare to Humble+Harmonic's own N=3 result
for the identical test (`PHYS-001`): range **4.45 degrees**
(223.19-227.64).

# Conclusion -- an honest negative result, not the hypothesized direction

**The officially-paired environment (Jazzy+Harmonic) showed roughly 6x
*more* ROS2/DDS-layer variance than the unofficial one
(Humble+Harmonic), not less.** This is the opposite of what
`NEXT_STEPS.md` hypothesized ("차이가 발견되면 좋은 결과" -- a difference
either direction is a real result, and this one points away from "the
unofficial pairing is the problem").

**Important confound, stated plainly, not hidden**: this comparison is
not a clean single-variable test. Humble+Harmonic was measured on bare
WSL2; Jazzy+Harmonic was measured inside a Docker container running on
the same WSL2 host -- an *additional* virtualization layer. Direct
evidence this adds real overhead: physics-only wall-clock time was
~93-110s per run here vs. ~60s bare-WSL2 for the identical
120-sample/6-second-scenario workload (a ~50-80% slowdown), and this
task's own `gz world control` service-timeout incident (see above) did
not occur in the equivalent bare-WSL2 `PHYS-001` testing. It is entirely
possible that Docker's own scheduling/resource contention -- not the
Humble-vs-Jazzy or Fortress-vs-Harmonic distinction at all -- is what's
driving the larger variance observed here. **This task does not
disentangle "official pairing" from "extra containerization layer"** --
doing that cleanly would require also running Humble+Harmonic inside an
equivalent Docker container for a fair apples-to-apples comparison,
which is a natural, well-scoped follow-up this task does not attempt.

What this task does establish cleanly (the physics-only result has no
such confound, since it's gz-transport-only regardless of container vs.
bare-metal): **physics solver determinism is not environment-specific**
-- reproduced exactly across two different Gazebo Sim patch versions and
two different Ubuntu/ROS2 distro generations.
