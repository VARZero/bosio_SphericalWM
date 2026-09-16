# BOSIO 외부 포인터 입력 API

BOSIO는 USB 마우스와 PYNQ 버튼뿐 아니라 별도 프로세스가 만든 포인터 입력도
받습니다. 관성 추적기, 카메라 손동작 인식기, 시선 추적기 같은 입력 데몬은
`bosio_input_client.py`로 구면 포인터를 움직이고 클릭이나 드래그를 전달할 수
있습니다. 입력 프로세스는 창을 만들거나 출력 코어를 직접 다루지 않습니다.

```text
관성 추적 데몬 ─┐
손동작 인식 데몬 ├─ 외부 입력 API ─ /tmp/bosio-wm.sock ─ 포커스·클릭·드래그
접근성 장치 ─────┘
```

## 필요한 파일

외부 입력 프로세스에는 표준 Python 라이브러리만 사용하는 다음 파일 하나가
필요합니다.

```text
bosio_input_client.py
```

## 가장 간단한 사용법

```python
from bosio_input_client import BosioInputClient

with BosioInputClient("camera-gesture") as pointer:
    pointer.move_absolute(azimuth=25.0, elevation=-18.0)
    pointer.click()
```

계속 추적하는 프로세스는 연결을 유지하고 새 측정값이 들어올 때만 호출합니다.

```python
with BosioInputClient("imu-pointer") as pointer:
    while True:
        yaw, pitch = read_tracker()
        pointer.move_absolute(yaw, pitch)
        if gesture_pressed():
            pointer.button(True)
        if gesture_released():
            pointer.button(False)
```

`button(True)` 이후 `move_absolute()` 또는 `move_relative()`를 반복하면 드래그가
됩니다. 프로세스가 버튼을 누른 상태에서 종료되거나 연결이 끊겨도 윈도우
데몬이 그 입력원에 속한 버튼을 자동으로 놓습니다.

## 함수

| 함수 | 역할 |
|---|---|
| `move_absolute(azimuth, elevation)` | 포인터를 방위각·고도각의 절대 위치로 이동 |
| `move_relative(delta_azimuth, delta_elevation)` | 현재 위치에서 각도 단위로 상대 이동 |
| `button(pressed, button="left")` | 누름 또는 놓기 전달; 드래그에 사용 |
| `click(button="left")` | 한 번의 누름과 놓기를 한 요청으로 전달 |
| `scroll(delta)` | 스크롤 변화량 전달 |
| `state()` | 현재 포인터 위치, 맞닿은 창, 눌린 버튼 상태 조회 |

각도는 도 단위입니다. 방위각은 `-180°..+180°`에서 이어지며 고도각은
`-89.5°..+89.5°`로 제한됩니다. 카메라 영상의 픽셀 좌표나 정규화 좌표는 입력
데몬에서 장치의 시야각과 보정값을 이용해 방위각·고도각으로 바꿔야 합니다.

`left`, `middle`, `right` 버튼을 사용할 수 있습니다. 여러 외부 입력원이 같은
버튼을 누른 경우 마지막 입력원이 놓을 때 전역 버튼 상태가 해제됩니다. 따라서
한 입력원이 끌기 동작 중일 때 다른 입력원의 상태 변경이 끌기를 갑자기 끝내지
않습니다.

## 실행 예제

현재 방향을 클릭합니다.

```bash
python3 bosio_input_demo.py --azimuth 0 --elevation -59
```

같은 위치에서 오른쪽으로 12° 끌어 봅니다.

```bash
python3 bosio_input_demo.py --azimuth 0 --elevation -59 --drag-degrees 12
```

## IPC 호출 이름

Python 이외의 언어에서는 기존 한 줄 JSON IPC에 다음 호출을 보낼 수 있습니다.

| 호출 | 주요 인자 |
|---|---|
| `input_warp` | `azimuth`, `elevation` |
| `input_move` | `delta_azimuth`, `delta_elevation` |
| `input_button` | `button`, `pressed` |
| `input_click` | `button` |
| `input_scroll` | `delta` |
| `input_status` | 없음 |

소켓은 기본적으로 `/tmp/bosio-wm.sock`이며 접근 권한은 윈도우 데몬 서비스의
`--socket-group` 설정을 따릅니다. 외부 입력 프로세스는 해당 그룹의 사용자로
실행해야 합니다.
