# Double Pendulum Control (ROS2 + Gazebo)

[English](README.md) | [한국어](README.ko.md)

ROS2(Humble) + Gazebo Sim(Harmonic)에서 2-DOF 이중 진자를 완전 직립(upright) 자세로
안정화하는 제어 프로젝트입니다. PD, 상태공간 선형화 + LQR 순서로 고전 제어를 먼저
검증하고, 이후 자동 평가 하네스를 거쳐 에이전틱 코딩 엔지니어링 레이어를 얹는 것을
목표로 합니다.

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
Robotics System         ROS2: state_estimator → controller → ros2_control
                        → Gazebo
────────────────────────────────────────────────────────────────────────
Control Engineering     이중 진자 동역학 · 선형화 · PD/LQR · 안정성 ·
                        상태 피드백 · 외란 · 액추에이터 포화
```

여기서 말하는 "self-evolving"이 정확히 무엇을 의미하고, 무엇을 의미하지 *않는지*
구체적인 예를 들면: 에이전트가 더 나은 `Kp`나 `Q` 값을 찾아내는 건 그냥 컨트롤러
튜닝일 뿐입니다. 진짜 harness의 진화라고 부를 수 있는 건, 에이전트가 **개발 습관
자체**를 학습하는 겁니다 — 예를 들어 URDF의 질량이나 링크 길이가 바뀔 때마다 LQR
게인 재계산을 반복해서 까먹는다면, harness가 *"URDF/Xacro 변경 → 재선형화 →
K 재계산 → regression 시나리오 재실행"* 같은 규칙을 제안하고, 이 규칙이 이후
작업들에서 실제로 그 실패를 줄이는 게 확인될 때만 계속 활성 상태로 남겨야 합니다
— 무조건 계속 쌓아서 지침 파일을 끝없이 늘리는 방식(이 설계가 피하려는
"catastrophic remembering" 문제)이 아니라는 뜻입니다.

이는 2026년 현재의 에이전틱 코딩 연구 흐름과 맞닿아 있습니다: 무조건 누적하는
대신 회귀 게이트를 통과해야 채택되는 skill, 채팅 맥락이 아니라 영속적 아티팩트로
남는 작업 계획과 결과(`private/roadmap.md`, `result.json`), 테스트 스위트가 아니라
실제 동역학 시뮬레이션이라는 진화 신호로서의 실행 가능한 물리 피드백, 그리고
에이전트의 쓰기 권한을 실시간 제어 경로와 아키텍처 수준에서 분리하는 것
(`disturbance.py`와 `run_experiment.py`의 docstring에 이 경계가 실제로 왜 중요한지
구체적인 사례가 나와 있습니다).

아래 Phase 0~3이 바로 그 루프를 가능하게 하는 제어 시스템과 평가 하네스를 만드는
단계입니다. 이 프로젝트는 세 단계 깊이로 설명할 수 있습니다: "ROS2 써봤어요" →
"Gazebo에서 이중 진자의 비선형 동역학을 구현하고 LQR 기반 자세 안정화를
구현했습니다" → "자동 시뮬레이션 + 제어 성능 평가 하네스를 만들었습니다" →
"그 하네스를 이용해 컨트롤러/ROS2 코드를 수정하고, 자신의 실패 이력에서 재사용
가능한 엔지니어링 규칙을 추출하는 코딩 에이전트를 만들었습니다" (Phase 3이
탄탄해진 다음, Phase 4부터).

## 현재 상태

- **Phase 0 (환경 셋업)** — 완료
- **Phase 1 (플랜트: URDF/Xacro, Gazebo spawn)** — 완료
- **Phase 2 (고전 제어: PD, 선형화, LQR)** — 완료, 실기 검증됨
- **Phase 3 (자동 평가 하네스)** — 진행 중 (metric 계산 + `result.json` 자동 판정까지 완료,
  LQR이 `nominal_balance` 시나리오에서 관절2 정착시간/오버슈트 기준 미달로 재튜닝 필요)
- Phase 4 이후(코딩 에이전트, self-evolving skill 등)는 Phase 3 완료 후 착수 예정

## 패키지 구조

| 패키지 | 역할 |
|---|---|
| `double_pendulum_description` | URDF/Xacro 모델(균일 막대 2개, 완전구동), Gazebo world, spawn launch |
| `double_pendulum_control` | PD/LQR 컨트롤러 노드, 선형화 모델, `ros2_control` 설정 |
| `double_pendulum_eval` | 재현 가능한 외란 테스트, metric 계산, 자동 평가(pass/fail) 러너, 시나리오 정의 |

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
