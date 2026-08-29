# Double Pendulum Control (ROS2 + Gazebo)

[English](README.md) | [한국어](README.ko.md)

**포트폴리오 사이트**: [bright-muffin-5e2b3e.netlify.app](https://bright-muffin-5e2b3e.netlify.app)
— 이 README와 같은 정직성 기준으로 만든 결과 시각화·다이어그램 페이지입니다
(미해결 문제도 그대로 보여줍니다).

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
| 3 — 자동 평가 하네스 | 시뮬레이션 → metric → `result.json` pass/fail, regression suite | ✅ 완료 — Phase 2의 미해결 이슈를 숨기지 않고 정확히 *잡아냄*(아래 한계 참고). 이제 이분법 pass/fail 대신 4가지 판정(`PASS_CONTROL`/`FAIL_CONTROL`/`INVALID_INFRA`/`FAIL_HARNESS`)으로 분리됨 — 아래 [실험 유효성 계층](#실험-유효성-계층) 참고 |
| 4 — 기본 코딩 에이전트 | task spec → PLAN.md → 코드 수정 → build → sim → 검증 | ✅ 5개 task 완료 (`CTRL-001`–`CTRL-005`) |
| 5 — Tool Architecture | structured robotics tool vs. raw bash | 🟨 6개 중 5개 완료(ROS graph inspection, run comparison 등); bash-vs-structured 비교실험만 보류 |
| 6 — Self-Evolving Harness | failure store → categorize → skill 제안 → regression-gated promote/reject | ✅ MVP 완료 — 실제 skill 하나를 끝까지 제안·평가했고, **두 번(N=3, N=8) 다 정직하게 REJECT** — 아래 참고 |
| 7 — Memory Lifecycle / Safety | skill retirement, stale rule detection, approval gate, sandbox policy, red-team 시나리오 | ✅ MVP 완료 — 이 프로젝트 자신의 도구에서 실제 취약점 2건 발견·수정(`SEC-001`, `SEC-002`) |

위 모든 Phase는 `tasks/` 아래 실제 task 디렉토리(spec, plan, result, evidence)로
뒷받침됩니다 — 근거 없는 상태 주장이 아닙니다.

## 실험 유효성 계층

후속 task 3개(`INFRA-001`–`003`)가 하네스 자신의 측정을 신뢰할 수 있게
만들었고, 거기에 더해 이 프로젝트의 run-to-run 변동성이 실제로 어디서
오는지 마침내 답한 task(`PHYS-001`) 하나가 더 있습니다:

- **`INFRA-001`** — 단순 pass/fail bool은 "컨트롤러가 진짜 실패한 것"과
  "실험 자체가 애초에 유효하게 실행되지 않은 것"(토크 0, 샘플 0, discovery
  timeout)을 같은 것으로 취급했습니다. 이제 모든 run은 4가지 판정
  (`PASS_CONTROL`/`FAIL_CONTROL`/`INVALID_INFRA`/`FAIL_HARNESS`) 중 하나를
  받고, `pass_rate`는 앞의 두 개로만 계산합니다 — 인프라/하네스 실패율은
  별도로 추적해서 제어 품질 숫자를 조용히 오염시키지 않습니다.
- **`INFRA-002`** — `run_clean_experiment.sh`에 남아있던 ad hoc `sleep`들을
  실제 readiness 신호(`/clock` 증가, `ros2 control list_controllers`의
  `active` 상태, publisher+subscriber 연결)를 폴링하는 방식으로 교체.
  검증 실행 중 실제 인프라 실패(`CTRL-005`가 이미 문서화한 FastRTPS
  `/dev/shm` 누적 문제)를 실시간으로 잡아냈습니다.
- **`INFRA-003`** — 모든 run/batch가 이제 격리된
  `results/raw/<run_id>/` 출력 디렉토리(이후 run에 절대 덮어써지지 않음)와
  environment manifest(ROS distro, Gazebo 버전, timestep/solver 설정)를
  갖습니다. 계획했던 반복 실행마다 다른 `ROS_DOMAIN_ID` 부여는 구현·테스트
  후 **되돌렸습니다** — 이 프로젝트의 WSL2+Gazebo+Humble 조합에서 `/clock`
  discovery 자체를 깨뜨리는 것을 실측으로 확인했기 때문입니다(조용히 남겨두지
  않고 문서화함).
- **`PHYS-001`** — 진짜 성과. 새 하네스가 Gazebo를 gz-transport로만
  직접 구동(pause/step/wrench/pose — ROS2/DDS 전혀 안 거침)하고 같은
  외란 프로파일을 오픈루프로 재생합니다. 결과, 서로 다른 3번의 독립적인
  Gazebo 재실행에서 **완전히 비트 단위로 동일한 궤적**(run당 120개 샘플
  전체에서 최대 차이 0.0 rad) — 제어 없이 진짜로 카오스적인 동역학인데도
  그렇습니다. 똑같은 시나리오를 기존 ROS end-to-end 경로(컨트롤러는 여전히
  없어서 DDS/`joint_state_broadcaster` 계층만 추가됨)로 돌리면 실제로 작지만
  0이 아닌 편차가 나타납니다(`overshoot_q1_deg`가 223.19°~227.64°, N=3).
  **물리 솔버는 결정론적입니다 — 이 프로젝트가 지금까지 관측한 모든
  run-to-run 변동은 물리가 아니라 ROS2/DDS/controller 계층에서 비롯됩니다**
  — 증상을 하나씩 고치며 추론한 게 아니라 직접 측정으로 확인한 결과입니다.
- **`ENV-001`** — 이 ROS2/DDS 계층 변동이 이 프로젝트의 비공식 조합인
  Humble+Harmonic에만 해당하는지 확인하려고, `PHYS-001`과 정확히 같은
  방법론을 **공식** 조합인 Jazzy+Harmonic 컨테이너 안에서 반복. 결과는
  가설과 정반대: 공식 조합 쪽이 **오히려 ~6배 더 큰 변동**(오버슈트 범위
  27.09° vs 4.45°, 각 N=3) — 진짜 교란요인을 숨기지 않고 명시한 정직한
  음성 결과(Jazzy+Harmonic은 Docker 안에서 테스트해서 Humble+Harmonic엔
  없던 가상화 계층이 하나 더 있었고, 그래서 "공식 조합"과 "컨테이너화
  오버헤드"가 아직 분리 안 됨). 두 환경 모두 동일하게 확인된 것: 물리
  솔버 결정론성(0.0 rad 차이, N=3) — 환경에 무관함.

전체 조사 기록과 증거는 `tasks/INFRA-001-verdict-taxonomy/`,
`tasks/INFRA-002-readiness-gate/`, `tasks/INFRA-003-run-isolation/`,
`tasks/PHYS-001-physics-only-harness/`, `tasks/ENV-001-distro-comparison/` 참고.

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
통과하는 것입니다. `PHYS-001`(위 [실험 유효성 계층](#실험-유효성-계층)
참고)이 나중에 확인한 바로는, ROS2/DDS/controller 계층에만 있는 별도의
작은(~4.45°) 진짜 편차도 있습니다. 실제로 배포된 LQI(적분항이 추가된
LQR, `lqr_node.py`)에 대해서는 이 "게인 튜닝이냐 ROS2 계층이냐" 질문을
"나중에 더 나누기"로 남겨두지 않고 완전히 근본원인까지 규명했습니다 —
다음 섹션 참고.

`REFACTOR-001`은 관련되지만 다른 위험을 닫았습니다: plant의 물리
파라미터(질량, 길이, damping, 토크 한계)와 LQR 게인 설계가 예전엔 각자
독립적으로 값을 하드코딩하고 있어서 둘이 어긋나도 아무것도 막지
않았습니다. 이제 둘 다 `plant_params.yaml` 하나를 읽고,
`lqr_node.py`는 그 파일이 바뀐 뒤 캐시된 게인을 재생성하지 않으면
(조용히 잘못된 게인으로 도는 대신) 명확한 `STALE GAIN` 에러로 실행 자체를
거부합니다 — 설계만 한 게 아니라 직접 테스트해서 확인했습니다. 이걸
기억해야 할 규칙으로 인코딩하고 있던 candidate skill
(`SKILL-CONTROL-MODEL-CONSISTENCY`, 위에서 언급한 두 번 REJECT된 그
skill — `HARNESS-001` 참고)은 이제 정식으로 retired 상태입니다, 그
규칙이 구조적으로 더는 필요 없어졌기 때문입니다.

전체 조사 기록은 `tasks/CTRL-003-pd-reproducibility/`,
`tasks/CTRL-004-statistical-acceptance/`,
`tasks/CTRL-005-run-reproducibility/`,
`tasks/PHYS-001-physics-only-harness/`,
`tasks/REFACTOR-001-plant-single-source/` 참고.

## 알려진 한계: LQI 정착 — 서로 독립적인 두 원인으로 근본원인 규명

`nominal_balance`에서 LQI의 실제 Gazebo 정착시간이 3.0초 기준 대비
3.3~3.4초에 머물러 있었고, 같은 컨트롤러 자신의 오프라인 모델 예측치와도
설명 안 되는 격차가 있었습니다. 후속 task 3개(`PHYS-002`, `CTRL-006`,
`DIAG-002`)가 이걸 근본원인까지 규명했습니다 — 하나의 깔끔한 이야기가
아니라, 서로 독립적으로 실재하며 겹쳐 있는 두 가지 원인으로. 더 깔끔한
서사가 되는 쪽으로 억지로 끼워맞추지 않고 나온 그대로 보고합니다.

- **`PHYS-002`**는 두 번째 physics-only 하네스를 만들었습니다 — 이번엔
  **closed-loop**: 캐시된 실제 LQI 게인·제어법칙을 gz-transport로 직접
  구동(루프 안에 ROS2/DDS 전혀 없음), 정확히 지터 없는 10ms 고정 제어
  주기로. 결과: **오프라인 모델과 physics-only 하네스가 거의 정확히
  일치**(정착 3.25초 vs 3.24초, 둘 다 3.0초 기준 미달) — 이 게인은
  이상적인 조건에서도 원래부터 살짝 느립니다, ROS2와 무관한 모델/튜닝
  문제. 그런데 **실제 ROS2 e2e는 둘 다보다 질적으로 더 나쁩니다**: 6초
  시나리오 창 안에서 아예 정착을 못 함(N=5, 유효 4개 run). 원인이
  하나가 아니라 둘이고, 겉보기처럼 단순히 더해지는 관계도 아닙니다 —
  다음 항목 참고.
- **`CTRL-006`**은 모델/튜닝 쪽을 고치려고 LQI 게인을 재탐색했습니다
  (`autotune_lqr.py`, `differential_evolution`). 오프라인에서는 극적으로
  성공 — 정착 3.25초 → 0.87초. 오프라인만 믿지 않고 실제 Gazebo로도
  배포·검증: **실제 run 5개 전부 실패, 게다가 여러 지표(팔꿈치 관절
  정착·오버슈트) 기준으로는 새 게인이 원래보다 오히려 더 나빴습니다** —
  더 공격적인 게인일수록 실제 시스템의 지연/지터에 대한 마진이 줄어든다는
  것과 일치. 원래 게인으로 되돌렸고, 새 게인의 전체 수치는 폐기하지 않고
  음성 결과로 그대로 문서화해뒀습니다.
- **`DIAG-002`**는 실제 궤적이 physics-only 궤적과 정확히 *언제* 벌어지는지
  짚었습니다. 개별 큰 지터 이벤트 근처가 아니었습니다(`DIAG-001`이 5~10ms
  명목 주기 대비 최대 6.8~9.5ms 지터를 실측했지만, 각 run 자신의 최악
  지터 시각이 그 run의 발산 시점을 예측하지 못함 — 이것도 유의미한 음성
  결과로 그대로 보고). 대신 발산 시작 시각이 physics-only 궤적 *자신의*
  정착 순간 직후로 매우 좁게 모여있습니다(+0.08~0.71초, 평균 +0.52초) —
  지터 이벤트 시각(run마다 전혀 안 겹치는 2.8~6.5초 범위)보다 훨씬 좁고
  일관된 패턴. 추정되는 메커니즘(아직 증명은 아님): 이 게인은 정착
  밴드에 막 진입하려는 그 순간이 가장 취약하고, 크고 단발적인 지연 하나가
  아니라 누적되는 작은 지터만으로도 그 창을 놓치게 만들기 충분합니다.

종합하면: 정착시간 격차에는 서로 독립적으로 확인된 두 원인이 있고
(아슬아슬한 게인 하나, 그리고 게인 튜닝만으로는 못 고치고 오히려
악화시킬 수 있는 진짜 ROS2/DDS 계층 열화 하나), 지터와 그 열화를 잇는
메커니즘도 이제 막연한 열린 질문이 아니라 구체적이고 반증 가능한 가설이
됐습니다. 전체 기록은 `tasks/PHYS-002-closed-loop-physics-only/`,
`tasks/CTRL-006-lqi-gain-retune/`, `tasks/DIAG-002-jitter-trajectory-correlation/`
참고.

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
  `PLAN.md`, `result.json`, `trajectory.jsonl`, `evidence/`. 현재까지
  22개 task 완료(`CTRL-001`–`006`, `TOOL-001`, `BENCH-001`–`003`,
  `HARNESS-001`, `SEC-001`–`002`, `INFRA-001`–`003`, `PHYS-001`–`002`,
  `REFACTOR-001`, `ENV-001`, `DIAG-001`–`002`).
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

# LQR은 먼저 캐시된 게인이 필요합니다 (REFACTOR-001) -- 최초 1회, ~1분:
ros2 run double_pendulum_control design_lqr_gains.py
ros2 run double_pendulum_control lqr_node.py           # 캐시 로드, 수 초 안에 시작
# (plant_params.yaml이 캐시 생성 이후 바뀌었으면 lqr_node.py가 STALE GAIN
# 에러로 실행 자체를 거부합니다 -- design_lqr_gains.py를 다시 돌리거나,
# -p auto_design:=true로 인라인 재계산(~1분)하도록 우회 가능)

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
