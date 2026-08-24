# Double Pendulum Control (ROS2 + Gazebo)

[English](README.md) | [한국어](README.ko.md)

ROS2(Humble) + Gazebo Sim(Harmonic)에서 **완전구동(fully actuated)** 2-DOF
이중 진자를 완전 직립(upright) 자세로 안정화하는 제어 프로젝트입니다. 그 위에
에이전틱 엔지니어링 레이어를
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
                                  메모리 내 topic 기록 → Control Metrics
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
| 2 — 고전 제어 | PD, 선형화, LQR, 초기조건/외란 테스트 | ✅ 완료 — 아래 [한계](#알려진-한계-pd-게인-튜닝) 참고 |
| 3 — 자동 평가 하네스 | 시뮬레이션 → metric → `result.json` pass/fail, regression suite | ✅ 완료 — Phase 2의 미해결 이슈를 숨기지 않고 정확히 *잡아냄*(아래 한계 참고). 다만 아직 이분법 pass/fail이라 제어 실패와 인프라 실패를 구분 못함 |
| 4 — 기본 코딩 에이전트 | task spec → PLAN.md → 코드 수정 → build → sim → 검증 | ✅ 5개 task 완료 (`CTRL-001`–`CTRL-005`) |
| 5 — Tool Architecture | structured robotics tool vs. raw bash | 🟨 6개 중 5개 완료(ROS graph inspection, run comparison 등); bash-vs-structured 비교실험만 보류 |
| 6 — Self-Evolving Harness | failure store → categorize → skill 제안 → regression-gated promote/reject | ✅ MVP 완료 — 실제 skill 하나를 끝까지 제안·평가했고, **두 번(N=3, N=8) 다 정직하게 REJECT** — 아래 참고 |
| 7 — Memory Lifecycle / Safety | skill retirement, stale rule detection, approval gate, sandbox policy, red-team 시나리오 | ✅ MVP 완료 — 이 프로젝트 자신의 도구에서 실제 취약점 2건 발견·수정(`SEC-001`, `SEC-002`) |

위 모든 Phase는 `tasks/` 아래 실제 task 디렉토리(spec, plan, result, evidence)로
뒷받침됩니다 — 근거 없는 상태 주장이 아닙니다.

## 알려진 한계: PD 게인 튜닝

*(이 섹션은 원래 미해결 run-to-run 재현성 위기를 다뤘습니다 — `CTRL-005`가
근본 원인을 찾아 해결했습니다, 아래 참고.)* 동일한 `nominal_balance`
시나리오에 대한 동일한 PD/LQR 실행이 예전엔 극단적으로 다른 결과를
냈습니다(`CTRL-003`은 3번의 "동일한" 연속 실행에서 `overshoot_q1_deg`
200.5, 26.8, 63.9를 관찰; `CTRL-004`의 통계적 판정 모드는 0/5 통과,
5번 중 2번은 토크를 거의 안 걺). 두 번의 조사(`CTRL-003`, `CTRL-004`,
그리고 Phase 6의 `N=8` 후속 조사)로도 원인을 못 찾았습니다.

**`CTRL-005`가 실제 원인을 찾아 고쳤고**, 물리나 DDS의 혼돈이 아니라
이 프로젝트 자신의 평가 코드에 있던 구체적인 측정 유효성 버그 2개
때문이었습니다. (1) PD 컨트롤러의 시작 경로엔 readiness 확인이
**아예 없었습니다**(LQR과 달리 그냥 2초 sleep) — 그래서 커맨드
토픽에 아직 연결 안 된 컨트롤러 상태로 실험이 시작될 수 있었고, run의
일부 동안 실제 토크가 0이었습니다. (2) `run_experiment.py`의 기록
스케줄이 실제 `/joint_states` 데이터 도착이 아니라 노드 *생성* 시점부터
카운트다운을 시작해서, discovery가 충분히 느리면 6초짜리 시나리오
전체를 샘플 0개로 날려버릴 수 있었습니다. 둘 다 blind wait 대신
능동적 readiness 확인으로 수정. 재검증(`pd`/`nominal_balance`,
N=7 clean run) 결과: `overshoot_q1_deg`가 이제 최대 **0.08도**
(16.32~16.40)밖에 안 벌어집니다 — 170도+가 아니라. 세 번째 실제
기여 요인(반복적인 `pkill -9`로 쌓이는 FastRTPS 공유메모리 잔여물)도
찾았지만 공유 파이프라인엔 의도적으로 고치지 않았습니다 — 그 메모리
영역은 프로젝트 범위가 아니라 머신 전체에 걸친 영역이라서입니다 —
이유와 단일 세션 환경에서의 정확한 수정법은
`tasks/CTRL-005-run-reproducibility/PLAN.md` 참고.

**아직 안 풀린 것, 숨기지 않고 명시**: 저 재현 가능한 7번의 clean run
중 어느 것도 `nominal_balance`를 실제로 **통과**하진 못합니다 —
`settling_time_q1_s`가 3.0초 기준에 대해 일관되게 3.3~3.4초입니다.
더 이상 미스터리가 아니라 그냥 평범하고 잘 정의된 게인 튜닝 문제일
뿐입니다(PD의 decentralized 법칙이 10~15% 정도 느리게 정착함) — 아직
안 닫힌 문제입니다. 진자는 실제로 눈으로 보이게 직립 안정화됩니다 —
Phase 2에서 PD와 LQR 둘 다 Gazebo GUI로 확인했습니다 — 남은 문제는
"서 있긴 하나"가 아니라 *자동화된, 정량적* 판정 기준을 안정적으로
통과하는 것입니다.

전체 조사 기록은 `tasks/CTRL-003-pd-reproducibility/`,
`tasks/CTRL-004-statistical-acceptance/`,
`tasks/CTRL-005-run-reproducibility/` 참고.

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

## 저자성 (Authorship)

컨트롤러/ROS2/평가 하네스/에이전틱 하네스 구현 코드는 거의 전부 코딩
에이전트(Claude, Claude Code 경유)가 작성했습니다. spec-first 워크플로우
아래에서: 모든 task는 에이전트가 뭔가를 구현하기 *전에* 사람이 검토
가능한 `specification.yaml`(목표, 허용/금지 변경, acceptance criteria)이
먼저 고정됐고, 그래서 에이전트가 나중에 "성공"의 정의를 스스로 바꿀 수
없습니다(이걸 기계적으로 강제하는 장치는 위 `SEC-001` 참고). 사람이 한
일: 프로젝트 범위·방향 결정, 각 task의 acceptance criteria 작성/승인,
애매하거나 경계선상인 결과의 해석(예: CTRL-003의 INCONCLUSIVE 판정,
HARNESS-001의 REJECT 결정, 이 README 자체의 "알려진 한계" 서술 방식
결정), 그리고 매 단계마다 에이전트의 작업을 검증 없이 그냥 받아들이지
않고 검토하는 것. "알려진 한계"나 `SEC-001`/`SEC-002` 발견 사항 같은
섹션이 존재하는 이유 자체가, 보기 좋은 결과들도 검토를 거쳐 여러 번
반려되거나 조건부로만 인정됐지 그냥 깨끗한 성공으로 보고되지 않았다는
증거입니다.

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
  기준 12개 task 완료(`CTRL-001`–`005`, `TOOL-001`, `BENCH-001`–`003`,
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
  한계를 숨기지 않고 명시: `--approved-by`는 이름만 기록할 뿐, 그 사람이
  실제로 검토했다는 걸 확인하지는 않습니다 — 아래 `SEC-002` 참고.
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
    확인되지 않기 때문입니다. **완전히 해결한 게 아니라 완화**한
    것입니다: denylist 키워드가 매칭되면 눈에 보이는 경고와 함께
    별도의 2차 플래그(`--acknowledge-safety-warning`)를 강제로 요구합니다.
    이건 경고를 조용히 놓치는 걸 막는 장치일 뿐 실질적 안전 증명은
    아닙니다 — 리뷰어가 제대로 이해 안 하고 그냥 플래그만 입력할 수도
    있고, denylist 키워드에 안 걸리는 절차는 그냥 통과합니다.

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
