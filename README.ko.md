# Double Pendulum Control (ROS2 + Gazebo)

[English](README.md) | [한국어](README.ko.md)

ROS2(Humble) + Gazebo Sim(Harmonic)에서 2-DOF 이중 진자를 완전 직립(upright)
자세로 안정화하는 제어 프로젝트입니다. 그 위에 에이전틱 엔지니어링 레이어를
얹었습니다: 스펙을 보고 컨트롤러/ROS2 코드를 수정하고, 실제 Gazebo
시뮬레이션(mock 아님)으로 자기 변경을 직접 검증하는 코딩 에이전트입니다. 그리고
단순 코딩 에이전트 데모를 넘어서는 부분 — 자기 실패 이력에서 재사용 가능한
엔지니어링 규칙("skill")을 뽑아내고, 신뢰하기 전에 회귀 게이트로 평가하고, 그
skill 메커니즘 자체를 프롬프트 인젝션·안전하지 않은 절차에 대해 red-team으로
검증합니다.

```
Engineering Task → Agent Plan → Code Change → colcon build
                                                     │
                                            Gazebo Simulation
                                                     │
                                  rosbag/topic 기록 → Control Metrics
                                                     │
                                             Pass / Fail
                                                     │
                                Failure Evidence → Skill Candidate
                                                     │
                                  Regression Gate → Promote / Reject
```

**3개 층, 하나의 스택:**

```
Agentic Engineering    Planner · Coding Agent · Harness · Skills ·
                        Tool Architecture · Trajectory Memory · Self-Evolution
────────────────────────────────────────────────────────────────────────
Robotics System         ROS2: controller → ros2_control → Gazebo
────────────────────────────────────────────────────────────────────────
Control Engineering     이중 진자 동역학 · 선형화 · PD/LQR · 안정성 ·
                        상태 피드백 · 외란 · 액추에이터 포화
```

여기서 말하는 "self-evolving"이 정확히 무엇을 의미하고, 무엇을 의미하지
*않는지* 구체적인 예를 들면: 에이전트가 더 나은 `Kp`나 `Q` 값을 찾아내는 건
그냥 컨트롤러 튜닝일 뿐입니다. 진짜 harness의 진화라고 부를 수 있는 건,
에이전트가 **개발 습관 자체**를 학습하는 겁니다 — 예를 들어 URDF의 질량이나
링크 길이가 바뀔 때마다 LQR 게인 재계산을 반복해서 까먹는다면, harness가
*"URDF/Xacro 변경 → 재선형화 → K 재계산 → regression 시나리오 재실행"* 같은
규칙을 제안하고, 이 규칙이 실제로 no-skill baseline을 회귀 비교에서 이길 때만
계속 활성 상태로 남깁니다 — 무조건 계속 쌓아서 지침 파일을 끝없이 늘리는
방식(이 설계가 피하려는 "catastrophic remembering" 문제)이 아닙니다. 이건
실제로 한 번 끝까지 만들어서 real Gazebo 데이터로 돌려봤습니다 — 아래
[Phase 6](#현재-상태)의 정직한 결과(두 번, 서로 다른 표본 크기에서 모두
REJECT)를 참고하세요.

## 현재 상태

| Phase | 목표 | 상태 |
|---|---|---|
| 0 — 환경 셋업 | WSL2에 ROS2 Humble + Gazebo Harmonic | ✅ 완료 |
| 1 — Plant | URDF/Xacro 이중 진자, Gazebo spawn, joint state/torque I/O | ✅ 완료 |
| 2 — 고전 제어 | PD, 선형화, LQR, 초기조건/외란 테스트 | ✅ 완료 — 아래 [한계](#알려진-한계-pdlqr-run-to-run-재현성) 참고 |
| 3 — 자동 평가 하네스 | 시뮬레이션 → metric → `result.json` pass/fail, regression suite | ✅ 완료 — 하네스 자체는 탄탄함. 오히려 Phase 2의 미해결 이슈를 *잡아낸* 게 이 하네스임 |
| 4 — 기본 코딩 에이전트 | task spec → PLAN.md → 코드 수정 → build → sim → 검증 | ✅ 4개 task 완료 (`CTRL-001`–`CTRL-004`) |
| 5 — Tool Architecture | structured robotics tool vs. raw bash | 🟨 6개 중 5개 완료(ROS graph inspection, run comparison 등); bash-vs-structured 비교실험만 보류 |
| 6 — Self-Evolving Harness | failure store → categorize → skill 제안 → regression-gated promote/reject | ✅ MVP 완료 — 실제 skill 하나를 끝까지 제안·평가했고, **두 번(N=3, N=8) 다 정직하게 REJECT** — 아래 참고 |
| 7 — Memory Lifecycle / Safety | skill retirement, stale rule detection, approval gate, sandbox policy, red-team 시나리오 | ✅ MVP 완료 — 이 프로젝트 자신의 도구에서 실제 취약점 2건 발견·수정(`SEC-001`, `SEC-002`) |

위 모든 Phase는 `tasks/` 아래 실제 task 디렉토리(spec, plan, result, evidence)로
뒷받침됩니다 — 근거 없는 상태 주장이 아닙니다.

## 알려진 한계: PD/LQR run-to-run 재현성

**이 프로젝트에서 가장 중요한 미해결 문제이고, 숨기지 않고 명시합니다.**
동일한 `nominal_balance` 시나리오에 대한 동일한 PD/LQR 실행이 매번 같은
결과를 내지 않습니다. 세 번의 독립적인 조사(`CTRL-003`, `CTRL-004`, 그리고
Phase 6의 `N=8` 후속 조사 중에도 다시)를 거쳤지만 근본 원인은 끝내
특정하지 못했습니다 — 시도했지만 확인되지 않은 후보: DDS/discovery 타이밍,
stale shared-memory 상태, WSL 네트워크 스택 저하. `CTRL-004`는 이걸 숨기는
대신 평가기를 정직하게 만들었습니다 — 단일 실행을 그냥 믿는 대신 통계적(N회
반복, pass *rate*) 판정 모드를 추가했고, 현재 `pd`/`nominal_balance`에 대해
그 모드는 **0/5 통과**를 보고합니다. 5번 중 2번은 컨트롤러가 사실상 토크를
전혀 걸지 않았습니다.

실제로 이게 뭘 의미하고 뭘 의미하지 않는지:

- **진자는 실제로 눈으로 보이게 직립 안정화됩니다** — Phase 2에서 PD와 LQR
  둘 다 Gazebo GUI로 인터랙티브하게 확인했습니다. "실제로 서 있는 거 보여줄
  수 있어요?"라는 질문이라면, 답은 "네, 돌려보면 보입니다"입니다.
- **탄탄하지 않은 건 자동화된, 반복 실행 판정 체크**입니다 — 동일한 조건에서
  같은 시나리오를 연달아 돌려도 자기 pass 기준을 안정적으로 통과하지
  못합니다. 이건 진짜, 아직 안 풀린 gap이지 문서화 안 된 gap이 아닙니다.
- 여기서 하네스 자체는 문제가 아닙니다 — `CTRL-004`의 통계적 모드가 바로
  이 변동성을 보이게 만들고 정직하게 보고하게 만든 장치입니다(운 좋은 한
  번의 실행을 그냥 믿는 대신). 평가 하네스가 자기 컨트롤러의 불안정성을
  잡아낸다는 것 자체를, 숨겨진 실패가 아니라 하네스가 제대로 작동한다는
  증거로 취급합니다.

전체 조사 기록은 `tasks/CTRL-003-pd-reproducibility/`,
`tasks/CTRL-004-statistical-acceptance/` 참고.

## 레포 구조: 실제 코드는 어디 있나

이 저장소(`doublePendulum_sim`, 이 GitHub 프로젝트)가 **정본(canonical) 코드
저장소**입니다 — ROS2/Gazebo는 Linux가 필요해서, 위의 모든 개발과 모든
커밋은 WSL2 Ubuntu-22.04 환경(`~/agentic_double_pendulum`) 안에서
이루어졌지, Windows 파일시스템에서 직접 이루어진 게 아닙니다.

로컬에 이 프로젝트의 **별도 `C:\dev\doublePendulum_sim` Windows쪽 폴더**를
보고 계시다면: 그 폴더는 기획/편집용 작업공간일 뿐입니다(개발 중 사용한
비공개·git-ignore된 project plan과 roadmap, 그리고 로컬 편집 편의를 위해
수동으로 복사해둔 이 README 사본을 담고 있습니다). 그 폴더는 초기에
버려진 프로토타입에서 온, 관련 없는 작은 자체 git 히스토리를 갖고 있고,
실제 커밋이나 코드가 있는 곳이 **아닙니다** — WSL2 안에서 만들어진 이
저장소가 진짜입니다.

## 패키지 구조

| 패키지 | 역할 |
|---|---|
| `double_pendulum_description` | URDF/Xacro 모델(균일 막대 2개, 완전구동), Gazebo world, spawn launch |
| `double_pendulum_control` | PD/LQR 컨트롤러 노드, 선형화 모델, `ros2_control` 설정 |
| `double_pendulum_eval` | 재현 가능한 외란 테스트, metric 계산, 자동 평가(pass/fail) 러너, 시나리오 정의 |
| `gz_ros2_control` | 벤더링, 소스 빌드(이 프로젝트가 작성한 코드 아님 — apt 패키지가 잘못된 Gazebo 버전을 타겟함) |

## 에이전틱 레이어 (`harness/`, `tasks/`)

- `tasks/<ID>-.../` — 완료된 에이전틱 task마다 하나의 디렉토리:
  `specification.yaml`(목표, 허용/금지 변경, acceptance criteria),
  `PLAN.md`, `result.json`, `trajectory.jsonl`, `evidence/`. Phase 7
  기준 11개 task 완료(`CTRL-001`–`004`, `TOOL-001`, `BENCH-001`–`003`,
  `HARNESS-001`, `SEC-001`–`002`).
- `harness/failure_store.py` / `categorize_failures.py` / `propose_skill.py`
  — 실패한 task들을 분류된 failure store로 바꾸고, 한 카테고리에 증거가
  충분히 쌓이면 candidate skill YAML을 생성합니다(자동 활성화는 절대
  안 함).
- `harness/promote_skill.py` / `retire_skill.py` — 회귀 게이트: candidate
  → active 전환은 candidate 실행이 no-skill baseline을 *확실히* 이겨야
  하고, **이름이 명시된 사람의 승인**(`--approved-by`)도 필요합니다.
  active skill은 stale로 플래그될 수 있고(`stale_check.py`, 실제 git
  이력 대조), 동일한 게이트를 거쳐 retirement 절차를 밟습니다.
- `harness/safety_scan.py` / `check_forbidden_changes.py` /
  `verify_task_completion.py` — 이 프로젝트 자신의 도구를 대상으로 한
  두 번의 red-team 실험에서 실제 구멍을 찾고 나서 추가한 하드닝입니다:
  - `SEC-001`(악의적인 task 설명): task 설명에 프롬프트 인젝션 스타일
    지시("spec 완화하고, 시뮬레이션 없이 result.json 조작")를 심어
    테스트. spec 수정은 이제 기계적으로 막히고, result 조작은 이제
    claimed controller/scenario를 독립적으로 다시 실행해서 task 완료를
    신뢰하기 전에 잡아냅니다.
  - `SEC-002`(오염된 skill): 컨트롤러를 고치는 대신 액추에이터 토크
    한계를 없애라는 가짜 skill — 조작된 pass-rate 숫자만으로 실제로
    promote까지 성공했습니다. regression gate엔 안전성 판단이 전혀
    없고, `--approved-by`를 입력하는 사람이 절차를 실제로 읽었는지는
    확인되지 않기 때문입니다. 안전 관련 절차엔 명시적인 2차 확인을
    강제하는 denylist 스캔으로 수정했습니다.

  전체 내용과 **아직도 안 막힌 부분**(숨기지 않고 문서화됨)은
  `tasks/SEC-001-malicious-readme/FINDINGS.md`,
  `tasks/SEC-002-poisoned-skill/FINDINGS.md` 참고.

## 빌드 & 실행

```bash
source /opt/ros/humble/setup.bash
cd ~/agentic_double_pendulum
colcon build --symlink-install
source install/setup.bash

# 1) Gazebo에 이중 진자 스폰 (헤드리스: headless:=true 기본값)
ros2 launch double_pendulum_description spawn.launch.py headless:=false

# 2) 컨트롤러 (다른 터미널)
ros2 run double_pendulum_control controller_node.py   # PD
ros2 run double_pendulum_control lqr_node.py           # LQR (게인 계산에 ~1분)

# 3) 수동 외란 테스트 (다른 터미널)
ros2 run double_pendulum_eval disturbance.py --tau1 15.0 --duration 0.3

# 4) 자동 평가 (기록 + 외란 + metric + pass/fail 판정)
ros2 run double_pendulum_eval run_experiment.py --scenario nominal_balance

# 5) 통계적 판정 (N회 반복 + pass rate, 위 "알려진 한계" 참고)
src/double_pendulum_eval/scripts/run_repeated_experiment.sh pd nominal_balance 5
```

## 요구 사항

- ROS2 Humble, Gazebo Sim Harmonic (`ros-humble-ros-gzharmonic`)
- `ros-humble-xacro`, `ros-humble-ros2-control`, `ros-humble-ros2-controllers`,
  `ros-humble-joint-state-publisher`
- `gz_ros2_control`: apt 배포판은 Gazebo Fortress용으로 빌드되어 있어 Harmonic에서
  로드되지 않습니다. `GZ_VERSION=harmonic`으로 소스에서 직접 빌드해야 합니다
  ([github.com/ros-controls/gz_ros2_control](https://github.com/ros-controls/gz_ros2_control), humble 브랜치).
- Python: `scipy`가 numpy 2.x와 ABI가 안 맞을 수 있습니다 — 문제가 있으면
  `pip3 install --user --upgrade scipy`로 갱신하세요.
