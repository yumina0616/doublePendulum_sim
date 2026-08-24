# Goal

Re-investigate CTRL-003's still-unexplained PD/LQR run-to-run
non-reproducibility with fresh eyes on the actual code, not another
infra-timing theory test (CTRL-003 already ruled out `real_time_factor`
and `use_sim_time` without resolving anything).

# Investigation

Read `controller_node.py`, `lqr_node.py`, `run_experiment.py`, and
`run_clean_experiment.sh` end to end looking for races, not assumptions.
Found three real, distinct issues, in order of how they surfaced:

## Bug 1: PD controller readiness was never actually checked

`run_clean_experiment.sh`'s LQR startup path polls its own log for "LQR
ready" (and, incidentally, gets ~60-90s of free discovery time from the
gain-design step). The **PD path had no such check at all** — just a
blind `sleep 2`. If ROS graph discovery for the PD node's
`/effort_controller/commands` publisher took longer than 2s (which this
WSL2 environment has shown it sometimes does), the experiment would start
with a controller that either wasn't running at all, or was running but
not yet connected to the command topic — meaning zero real torque for
part or all of the run. This matches CTRL-004's own observation of
"2 of 5 runs show max_abs_tau1_nm=0.0."

**Fix**: replaced the PD path's blind sleep with an active poll (same
style as the existing `/joint_states` check) confirming
`/effort_controller/commands` is actually being published before
proceeding.

## Bug 2: run_experiment.py started its schedule clock before real data arrived

`ExperimentRunner._on_tick` fires on a 0.02s timer starting at node
construction. `_now_s()` lazily sets `t0` (the schedule's zero-point) on
its *first call* — and since the timer fires almost immediately while
`/joint_states` discovery can take several seconds, `_on_tick` (not a
real data callback) was usually what set `t0`. Net effect: the
settle/disturbance/total_duration schedule started counting down from
node startup, not from real data flow. A slow-enough discovery could burn
through the whole scenario before a single sample was ever recorded —
confirmed directly: one run recorded `n_samples_joint_states=0,
n_samples_effort=0` for the entire 6s scenario, despite
`run_clean_experiment.sh`'s own pre-checks (a *different* node's
`ros2 topic echo`) having already confirmed both topics were flowing.

**Fix**: `_on_tick` now returns immediately (does nothing) until the
first real `/joint_states` message has arrived, so `t0` can only be set
by real data. Also added a 30s startup safety timeout (distinct exit code
6) so a genuine total discovery failure aborts cleanly instead of hanging.

## Bug 3 (identified, NOT permanently fixed): FastRTPS shared-memory accumulation

While testing bugs 1-2's fix, batches still degraded partway through: the
first 4-5 runs of an 8-run batch would be clean and highly consistent,
then later runs would hit "no /joint_states"/"controller never published"
infra failures again, with `RTPS_TRANSPORT_SHM ... open_and_lock_file
failed` errors in the logs. Direct inspection of `/dev/shm` confirmed the
mechanism: `run_clean_experiment.sh`'s cleanup step uses `pkill -9`
(SIGKILL), which does not give FastRTPS's shared-memory transport a
chance to release its `/dev/shm/fastrtps_*` segments cleanly. These
accumulate across repeated launch/kill cycles within one session (found
44 stale entries after a few hours of this session's testing, some
literally corrupted -- `ls` couldn't even `stat` them), and a later
process reusing an overlapping port then fails to open its own shared
memory. `/dev/shm` was observed to go from 0 to 80 entries within a
single 8-run batch even with bugs 1-2 fixed.

**Not fixed permanently**: clearing `/dev/shm/fastrtps_*` between runs
would fix this, but that shared-memory space isn't scoped to this
project — it's shared by every ROS2 process on the machine at the same
DOMAIN_ID, including any other concurrent session. Per explicit user
direction (a real collision with another concurrent Claude Code session
happened mid-investigation), this cleanup was only ever applied manually,
one-off, for this investigation's own batches — never added to
`run_clean_experiment.sh` itself. Documented here as a known, real,
reproducible factor for anyone chasing this again, with the exact
mechanism and fix if a single-tenant environment (e.g. CI, a dedicated
VM) makes it safe to apply.

## Side note: an unrelated permission bug during this investigation

Editing `run_experiment.py` via a Windows-side tool through the WSL UNC
path (`\\wsl.localhost\...`) silently stripped the file's executable bit
(`rwxr-xr-x` -> `rw-r--r--`), which `ros2 run` requires for a Python
entry point in an ament_python `--symlink-install` package. This produced
a misleading `No executable found` failure across an entire batch that
had nothing to do with any of the three bugs above. Fixed with `chmod +x`
and re-verified. Worth remembering for any future edit made the same way.

# Results

N=7 valid runs (of 8 attempted; 1 infra-aborted cleanly, no bad data),
`pd`/`nominal_balance`, both fixes + per-run `/dev/shm` clearing:

| run | overshoot_q1_deg | overshoot_q2_deg | settling_time_q1_s | max_abs_tau1_nm | stable |
|---|---|---|---|---|---|
| 1 | 16.40 | 11.49 | 3.365 | 23.94 | true |
| 2 | 16.32 | 11.10 | 3.339 | 23.76 | true |
| 3 | 16.32 | 11.10 | 3.411 | 23.78 | true |
| 4 | 16.33 | 11.07 | 3.409 | 23.78 | true |
| 5 | 16.38 | 11.09 | 3.383 | 23.88 | true |
| 6 | 16.32 | 11.31 | 3.342 | 23.76 | true |
| 7 | 16.32 | 11.27 | 3.328 | 23.76 | true |

Compare to CTRL-003's baseline (N=3, no fixes): overshoot_q1_deg = 200.49,
26.78, 63.93 -- wild, unstructured variance, one catastrophic. And
CTRL-004's N=5: 0/5 pass, 2/5 with `max_abs_tau1_nm=0.0` (no real torque
applied at all).

# Conclusion

The "chaotic" run-to-run variance was **not genuine physics/control
chaos** -- it was almost entirely explained by two concrete, fixable
measurement-validity bugs (controller readiness never confirmed;
recording schedule starting before real data). With both fixed (plus the
known-but-not-permanently-applied `/dev/shm` factor controlled for),
`pd`/`nominal_balance` is now highly reproducible: overshoot_q1_deg
varies by at most ~0.08 degrees across 7 runs, not by 170+ degrees.

None of the 7 runs actually **pass** `nominal_balance`'s acceptance
criteria -- `settling_time_q1_s` consistently lands at 3.3-3.4s against a
3.0s max, a small, *consistent* miss. This is the honest remaining state:
what looked like an unexplained reproducibility crisis is now a
mundane, ordinary gain-tuning gap (PD's decentralized law settles ~10-15%
too slowly), which is a well-posed, tractable problem -- not a mystery.
