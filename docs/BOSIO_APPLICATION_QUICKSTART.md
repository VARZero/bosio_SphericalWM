# BOSIO 애플리케이션 빠른 시작

이 문서는 PYNQ-Z2에서 실행 중인 BOSIO 윈도우 데몬에 애플리케이션을 연결하는
방법을 설명합니다. 애플리케이션은 bitstream, HDMI, AXI 레지스터와 DMA를 직접
다루지 않습니다. 데몬이 출력 코어를 소유하고, 애플리케이션은 Unix socket IPC로
창 상태와 RGB surface만 전달합니다.

## 동작 구조

```text
내 애플리케이션
  └─ bosio_wm_client.py
       └─ /tmp/bosio-wm.sock
            └─ bosio-window-manager.service
                 ├─ 구면 창 합성
                 ├─ C++/NEON dirty tile 패킹
                 └─ 출력 코어 DMA → HDMI
```

PYNQ-Z2가 부팅되면 systemd가 먼저 PYNQ 초기화와 `bootpy.service`를 끝내고,
그 다음 BOSIO 데몬이 BS23 bitstream을 로드합니다. 애플리케이션은 데몬이
준비된 후 창을 생성하면 됩니다.

## 준비 확인

PYNQ-Z2에서 다음을 실행합니다.

```bash
systemctl is-enabled bosio-window-manager.service
systemctl is-active bosio-window-manager.service
test -S /tmp/bosio-wm.sock && echo SOCKET_READY
```

`active`와 `SOCKET_READY`가 나오면 애플리케이션을 실행할 수 있습니다.

```bash
cd /home/xilinx/bosio_v2
export PYTHONPATH=/home/xilinx/bosio_v2
```

보드에 전체 저장소를 복제하지 않는 경우 애플리케이션 디렉터리에 다음 파일만
복사해도 됩니다.

```text
bosio_wm_client.py
```

클라이언트는 RGB 배열 처리를 위해 NumPy를 사용합니다.

## 첫 창 만들기

다음 파일을 `hello_bosio.py`로 저장합니다.

```python
import time
import numpy as np

from bosio_wm_client import BosioWMClient


with BosioWMClient("hello-app") as wm:
    window = wm.create_window(
        title="HELLO",
        azimuth=0,
        elevation=-59,
        width_deg=36,
        height_deg=24,
        surface_width=320,
        surface_height=200,
    )
    window_id = window["window_id"]

    image = np.zeros((200, 320, 3), dtype=np.uint8)
    image[:, :] = (30, 90, 180)
    wm.update_surface(window_id, image)

    time.sleep(10)
```

실행합니다.

```bash
python3 hello_bosio.py
```

창 중심은 `azimuth`, `elevation`으로 정합니다. `width_deg`, `height_deg`는
구면 공간에서의 창 크기이고, `surface_width`, `surface_height`는 애플리케이션이
그릴 로컬 이미지 해상도입니다.

현재 참조 GY-521 장착 방향에서는 고도 `-59°` 부근이 화면 중심입니다. 센서를
케이스에 다른 방향으로 넣으면 이 값은 설치 방향에 맞춰 바꿉니다.

## 이미지 갱신

`update_surface()`는 `height × width × 3` 형태의 RGB `uint8` NumPy 배열을
받습니다.

```python
frame = np.zeros((200, 320, 3), dtype=np.uint8)
frame[:, :, 0] = 255
wm.update_surface(window_id, frame)
```

이 호출은 전체 창 surface를 변경합니다. 작은 영역만 바뀌는 GUI는 부분 영역을
전달하십시오.

```python
button = np.full((24, 80, 3), (240, 120, 20), dtype=np.uint8)
wm.update_surface(window_id, button, x=32, y=40)
```

데몬은 dirty rectangle을 누적하고, C++ 합성기는 해당 영역과 교차하는 셀만
계산합니다. 출력 코어에는 실제로 색이 바뀐 타일만 BPT1 패킷으로 전송됩니다.
창 이동, 포커스, z-order 변경처럼 합성 구조가 바뀌면 데몬이 자동으로 전체
장면을 다시 만듭니다.

## 1초마다 이미지를 바꾸는 예제

저장소의 [bosio_wm_image_demo.py](../sw/bosio_wm_image_demo.py)를 실행하면
1초마다 색상 패턴이 바뀌고 클릭 좌표가 터미널에 출력됩니다.

```bash
python3 bosio_wm_image_demo.py
```

다른 위치에서 실행하려면 다음처럼 인자를 지정합니다.

```bash
python3 bosio_wm_image_demo.py \
  --width 640 --height 400 \
  --azimuth 45 --elevation -20
```

## 마우스와 포커스 이벤트

애플리케이션은 자신의 이벤트 큐를 주기적으로 읽습니다.

```python
for event in wm.poll_events():
    if event["type"] == "focus":
        print("focused:", event["focused"])

    elif event["type"] == "pointer_motion":
        # u, v는 창 내부의 0.0~1.0 상대 좌표
        x = int(event["u"] * 320)
        y = int(event["v"] * 200)
        print("move:", x, y, event["zone"])

    elif event["type"] == "pointer_button":
        x = int(event["u"] * 320)
        y = int(event["v"] * 200)
        print("click:", event["pressed"], x, y)
```

`zone`은 `title` 또는 `content`입니다. 제목 영역을 누른 상태에서 이동하면
윈도우 매니저가 창 이동을 처리합니다. 애플리케이션은 보통 `content` 이벤트만
자체 GUI 입력으로 사용하면 됩니다.

물리 마우스가 연결되지 않은 테스트에서는 클라이언트로 포인터를 직접 움직일
수 있습니다.

```python
wm.pointer_warp(azimuth=10, elevation=-59)
wm.pointer_button(True, "left")
wm.pointer_button(False, "left")
```

## 창 이동과 포커스

```python
wm.configure_window(
    window_id,
    azimuth=30,
    elevation=-45,
    roll=15,
)
wm.focus_window(window_id)
wm.raise_window(window_id)
```

창을 숨겼다가 다시 표시할 수도 있습니다.

```python
wm.configure_window(window_id, mapped=False)
wm.configure_window(window_id, mapped=True)
```

한 애플리케이션이 여러 창을 만들 수 있고, 애플리케이션마다 별도의
`BosioWMClient` 연결을 사용할 수 있습니다. 연결이 닫히면 데몬은 그 연결이
소유한 창을 자동으로 정리합니다.

## GUI 툴킷 연결

Qt, GTK, SDL, Dear ImGui, Pillow, OpenCV 등 어떤 GUI 툴킷도 최종 렌더링 결과를
RGB 배열로 만들 수 있으면 연결할 수 있습니다.

```text
GUI widget 또는 offscreen framebuffer
        ↓ RGB888 uint8 배열
BosioWMClient.update_surface()
        ↓
구면 투영 및 dirty tile 합성
```

GUI toolkit의 전체 화면을 매번 전송하기보다 변경된 damage region만 잘라
`x`, `y`와 함께 전달하는 것이 좋습니다. PYNQ-Z2에서 16×16 또는 32×32 정도의
국소 변경은 현재 구현에서 부분 타일 경로를 사용합니다.

## 종료 처리

`with BosioWMClient(...)`를 사용하면 예외나 정상 종료 시 소켓이 닫힙니다.
직접 객체를 만들었다면 반드시 `close()`를 호출하십시오.

```python
wm = BosioWMClient("my-app")
try:
    # application loop
    pass
finally:
    wm.close()
```

## 다른 PC에서 실행할 때

현재 클라이언트는 PYNQ-Z2의 Unix socket을 사용하므로 기본 실행 위치는
PYNQ-Z2입니다. PC GUI를 사용하려면 PYNQ-Z2에서 TCP 또는 WebSocket 게이트웨이를
실행하고, 게이트웨이가 `/tmp/bosio-wm.sock`으로 연결하도록 구성합니다.

화면 갱신은 JSON Base64보다 binary WebSocket 또는 shared memory 방식이
효율적입니다. 외부 네트워크에 게이트웨이를 열 때는 인증 토큰과 접근 가능한
인터페이스를 제한하십시오.

## 문제 해결

소켓이 없으면 데몬 상태와 부팅 로그를 확인합니다.

```bash
systemctl status bosio-window-manager.service --no-pager
journalctl -u bosio-window-manager.service -b --no-pager
```

창이 보이지 않으면 센서 장착 방향에 맞게 `azimuth`와 `elevation`을 조정합니다.
참조 보드에서는 `elevation=-59`가 기본 시야 중심입니다.

`FileNotFoundError: /tmp/bosio-wm.sock`가 나오면 데몬이 아직 실행되지 않았거나
부팅 초기화 중입니다. 다음 명령으로 확인할 수 있습니다.

```bash
systemctl is-active bosio-window-manager.service
test -S /tmp/bosio-wm.sock && echo SOCKET_READY
```

출력 코어의 bitstream과 DMA는 애플리케이션에서 직접 초기화하지 마십시오.
하드웨어 소유권은 `bosio-window-manager.service`가 유지합니다.
