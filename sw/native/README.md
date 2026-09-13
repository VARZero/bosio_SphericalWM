# BOSIO C++/NEON compositor

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
변경 시 미리 변환한 창별 RGB332 surface와 투영 LUT로 palette, tile directory,
활성 tile payload를 DMA word 배열에 바로 기록한다. 기존
`bosio_compositor_render()`와 `bosio_pack_scene()` API도 참조 검증과 NumPy
fallback 경로를 위해 유지한다.

`bosio_compositor_render_patch()`는 창마다 누적된 dirty rectangle과 투영 LUT를
대조하여 실제로 보이는 셀만 갱신한다. 출력 cache의 기존 directory offset을
유지할 수 있으면 변경 타일만 `BPT1` 패킷으로 만든다. 창 위치·z-order·포커스·
포인터 또는 타일 활성 구조가 달라지면 `-3`을 반환하고 Python 바인딩이 전체
packed 장면을 다시 생성한다.

네이티브 라이브러리를 로드할 수 없으면 윈도우 매니저는 기존 NumPy 합성기로
자동 전환한다.
