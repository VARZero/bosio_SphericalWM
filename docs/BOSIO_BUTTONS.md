# PYNQ-Z2 버튼 입력

현재 비트스트림은 PYNQ-Z2의 `BTN0`부터 `BTN3`까지를 독립적인 4비트 AXI GPIO
입력으로 제공한다. 이 장치는 출력 코어와 센서 허브 RTL에 포함되지 않은 표준
Xilinx IP이며, 물리 주소 `0x41200000`에서 읽을 수 있다.

| 비트 | 보드 버튼 | FPGA 핀 | 눌렀을 때 |
|---:|---|---|---:|
| 0 | BTN0 | D19 | 1 |
| 1 | BTN1 | D20 | 1 |
| 2 | BTN2 | L20 | 1 |
| 3 | BTN3 | L19 | 1 |

## 데몬 없이 Linux에서 읽기

FPGA에 현재 비트스트림이 올라간 상태에서 다음 명령을 실행한다. 이 도구는 Python
표준 라이브러리와 `/dev/mem`만 사용하며, 윈도우 매니저나 PYNQ API를 불러오지
않는다. `/dev/mem` 접근 권한 때문에 일반적으로 `sudo`가 필요하다.

```bash
cd /home/xilinx/bosio_v2
sudo python3 bosio_buttons.py --once
sudo python3 bosio_buttons.py
```

`--once`는 현재 버튼 마스크를 출력한다. 두 번째 명령은 5 ms마다 읽고 30 ms
디바운스를 적용해 눌림·뗌 이벤트를 계속 출력한다.

## 데몬 이벤트 API

데몬은 같은 입력을 읽어 최근 256개의 전역 버튼 엣지를 보관한다. 창 소유권이나
포커스와 무관하며, 각 클라이언트는 연결 시점부터 별도 이벤트 커서를 사용한다.
따라서 한 프로그램의 조회가 다른 프로그램의 이벤트를 제거하지 않는다.

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

`get_button_state()`는 `state`, `available`, `last_event_id`를 반환한다. 각 이벤트에는
`id`, `type`, `button`, `name`, `pressed`, `state`, `monotonic_ns`가 들어간다.
현재는 BTN0 등에 홈이나 설정 의미를 부여하지 않았다. UI가 결정되면 BoAYo 셸이
이 이벤트를 원하는 동작으로 매핑하면 된다.
