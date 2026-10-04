# BOSIO C++/NEON 합성기

`bosio_compositor.cpp`는 Cortex-A9용 구면 창 합성 및 RGB332 장면 패킹
라이브러리다. Python 데몬은 `ctypes` 바인딩인 `bosio_native_compositor.py`로
호출한다.

```bash
cd /home/xilinx/bosio_v2
./native/build_pynq.sh
```

빌드 결과는 `libbosio_compositor.so`다. 창 위치·크기가 바뀔 때만 전체 구면
투영 LUT를 생성하고, 표면 변경 시에는 저장된 destination cell과 source pixel
index를 재사용한다. ARM NEON은 셀 방향 dot product, 포인터 mask, RGB888에서
RGB332 변환에 사용된다.

`bosio_compositor_render_packed()`는 24비트 구면 중간 이미지를 만들지 않는다.
창별 RGB 표면과 투영 LUT로 셀 면적에 맞춘 bilinear·적응형 4×4 AA를 계산하고,
그 결과를 RGB332로 양자화해 팔레트·타일 디렉터리·활성 타일 데이터를 패킹한다.
창 외곽에서는 커버리지에 따라 아래 장면과 혼합한다. 기존
`bosio_compositor_render()`와 `bosio_pack_scene()` API도 참조 검증과 NumPy
fallback 경로를 위해 유지한다.

`bosio_compositor_render_patch()`는 창마다 누적된 dirty rectangle과 투영 LUT를
대조하여 실제로 보이는 셀만 갱신한다. 출력 cache의 기존 directory offset을
유지할 수 있으면 변경 타일만 `BPT1` 패킷으로 만든다. 창 위치·z-order·포커스·
포인터 또는 타일 활성 구조가 달라지면 `-3`을 반환하고 Python 바인딩이 전체
packed 장면을 다시 생성한다. AA 외곽 셀이 아래 창 색에 의존하는 변경도
안전하게 전체 장면으로 전환한다.

BS25에서는 Python 드라이버가 전체 패킹 결과를 비활성 DDR 장면에 기록한다.
BPT1은 같은 버퍼의 변경 타일만 수정하며, 코어가 프레임 경계에서 새 주소로
전환한 뒤 이전 버퍼에도 변경을 반영한다. 합성기에서 BPT1을 코어로 직접
전송하지 않는다. M=8/16/32 전체 구면을 담을 수 있는 출력 버퍼 상한을 사용하며,
BS24의 BRAM 용량 제한은 드라이버에서 별도로 검사한다.
[DDR 캐시 문서](../../docs/BOSIO_DDR_CACHE.md)와
[소프트웨어 AA 설명](../../docs/BOSIO_ANTIALIASING.md)을 참고한다.

네이티브 라이브러리를 로드할 수 없으면 윈도우 매니저는 기존 NumPy 합성기로
자동 전환한다.
