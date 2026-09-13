# PYNQ-Z2 버튼 입력

현재 비트스트림은 PYNQ-Z2의 `BTN0`부터 `BTN3`까지를 4비트 AXI GPIO 입력으로
제공한다. 이 장치는 출력 코어와 센서 허브의 RTL에 포함되지 않은 독립적인 표준
Xilinx IP이며, 리눅스 프로그램이 물리 주소 `0x41200000`에서 읽을 수 있다.
독립 실행 도구는 파이썬 표준 라이브러리와 `/dev/mem`만 사용하므로 PYNQ API나
BOSIO 데몬이 필요하지 않다. FPGA에는 현재 비트스트림이 올라가 있어야 한다.

| 비트 | 보드 버튼 | FPGA 핀 | 눌렀을 때 |
|---:|---|---|---:|
| 0 | BTN0 | D19 | 1 |
| 1 | BTN1 | D20 | 1 |
| 2 | BTN2 | L20 | 1 |
| 3 | BTN3 | L19 | 1 |

## 데몬 없이 Linux에서 읽기

비트스트림이 PL에 올라간 상태라면 표준 Python 라이브러리의 `/dev/mem` 매핑만
사용해 현재 상태를 읽거나 엣지 이벤트를 계속 볼 수 있다. 이 경로는 구면 윈도우
매니저나 출력 코어 드라이버를 불러오지 않는다.

```bash
sudo python3 bosio_buttons.py --once
sudo python3 bosio_buttons.py
```

첫 명령은 `BTN0..BTN3` 상태를 16진수 비트 마스크로 출력한다. 두 번째 명령은
5 ms마다 입력을 읽고 30 ms 디바운스를 거쳐 `pressed`와 `released`를 출력한다.
`--poll-ms`와 `--debounce-ms`로 이 값을 바꿀 수 있다.

## 데몬 이벤트 API

데몬은 같은 입력을 읽어 최대 256개의 전역 버튼 엣지를 보관한다. 이벤트를
읽어도 다른 클라이언트의 이벤트가 사라지지 않는다. SDK는 연결 시점의 이벤트
ID를 기억하므로 각 이벤트를 해당 클라이언트에 한 번씩 반환한다.

```python
import time
from bosio_wm_client import BosioWMClient

with BosioWMClient("boayo-shell") as client:
    print(client.get_button_state())
    while True:
        for event in client.poll_button_events():
            print(event["name"], event["pressed"], event["state"])
        time.sleep(0.01)
```

각 이벤트에는 `id`, `type`, `button`, `name`, `pressed`, `state`,
`monotonic_ns`가 들어간다. 아직 BTN0 등에 홈이나 설정 의미를 부여하지 않았다.

비트스트림과 HWH가 이미 올라간 상태에서는 창 관리자 없이도 다음처럼 읽는다.
`/dev/mem` 접근 권한이 필요하므로 일반적인 PYNQ 설정에서는 `sudo`를 사용한다.

```bash
sudo python3 bosio_buttons.py --once
sudo python3 bosio_buttons.py
```

첫 명령은 현재 마스크만 출력한다. 두 번째 명령은 5 ms마다 읽고 30 ms 동안
같은 값이 유지된 경우에만 `pressed` 또는 `released` 경계를 출력한다.

데몬은 같은 판독기를 사용해 최근 256개 경계를 전역 기록으로 유지한다. 이 기록은
창의 소유권이나 포커스와 무관하다. 각 클라이언트는 연결 시점의 이벤트 번호부터
독립적으로 읽으므로 다른 프로세스가 먼저 읽어도 이벤트가 사라지지 않는다.

```python
import time
from bosio_wm_client import BosioWMClient

with BosioWMClient("button-test") as client:
    print(client.get_button_state())
    while True:
        for event in client.poll_button_events():
            print(event["name"], "pressed" if event["pressed"] else "released")
        time.sleep(0.01)
```

현재 상태를 한 번 읽으려면 다음과 같이 실행한다.

```console
sudo python3 bosio_buttons.py --once
```

30 ms 디바운스를 적용한 눌림·뗌 이벤트를 계속 보려면 다음과 같이 실행한다.

```console
sudo python3 bosio_buttons.py
```

데몬 IPC에서는 `get_button_state()`와 `poll_button_events()`를 사용할 수 있다.

```python
from bosio_wm_client import BosioWMClient

with BosioWMClient("button-example") as client:
    print(client.get_button_state())
    while True:
        for event in client.poll_button_events():
            print(event)
```

`poll_button_events()`는 클라이언트별 이벤트 번호를 유지한다. 따라서 여러
프로그램이 동시에 읽어도 한 프로그램의 조회가 다른 프로그램의 이벤트를
삭제하지 않는다. 데몬은 5 ms마다 입력을 읽고 30 ms 동안 값이 유지될 때만
`pressed` 또는 `released` 이벤트를 확정한다.

## 데몬 없이 리눅스에서 읽기

FPGA에 BOSIO 비트스트림이 이미 올라간 상태에서 다음 명령을 실행한다. 이 도구는
윈도우 매니저 IPC를 사용하지 않고 AXI GPIO를 직접 읽는다.

```bash
cd /home/xilinx/bosio_v2
sudo /usr/local/share/pynq-venv/bin/python3 bosio_buttons.py --once
sudo /usr/local/share/pynq-venv/bin/python3 bosio_buttons.py
```

`--once`는 현재 4비트 마스크만 출력한다. 두 번째 명령은 5 ms마다 입력을 읽고
30 ms 디바운스를 거친 눌림·뗌 이벤트를 계속 출력한다.

파이썬 코드에서는 다음처럼 직접 사용할 수 있다.

```python
from bosio_buttons import BosioButtons

buttons = BosioButtons.from_address()
mask = buttons.read_state()
if mask & (1 << 0):
    print("BTN0 is down")
```

## 윈도우 매니저 데몬 이벤트

데몬도 같은 장치를 5 ms 주기로 읽고 30 ms 동안 안정된 신호만 이벤트로 인정한다.
버튼 이벤트는 창, 포커스, UI와 연결하지 않는다. 최근 256개를 전역 기록으로
보관하며 각 클라이언트가 별도 이벤트 커서를 가지므로 여러 프로그램이 동시에
읽을 수 있다.

```python
import time
from bosio_wm_client import BosioWMClient

with BosioWMClient("button-example") as client:
    print(client.get_button_state())
    while True:
        for event in client.poll_button_events():
            print(event)
        time.sleep(0.01)
```

이벤트 형식은 다음과 같다.

```json
{
  "id": 12,
  "type": "button",
  "button": 0,
  "name": "BTN0",
  "pressed": true,
  "state": 1,
  "monotonic_ns": 123456789
}
```

`get_button_state()`는 `state`, `available`, `last_event_id`를 반환한다. UI 설계가
확정되면 BoAYo 셸이 이 이벤트를 받아 홈·설정 등의 동작으로 매핑하면 된다.
