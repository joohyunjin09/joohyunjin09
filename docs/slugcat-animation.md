# README 안의 흰색 슬러그캣

흰색 슬러그캣 **한 마리**의 움직임을 빌드 시점에 절차적으로 계산하여, 외부 의존성이 없는 SVG 이미지로 저장한다. 방문자의 브라우저는 저장된 SVG 트랙을 재생·보간할 뿐 물리 엔진이나 JavaScript 앱을 실행하지 않는다.

## 참고한 원본과 재구성 범위

읽기 전용으로 분석한 저장소: [leesiuuuu/Slugcat-In-My-Monitor](https://github.com/leesiuuuu/Slugcat-In-My-Monitor/tree/7a5d106fa569f877579634a262b1b7e9e3c2c20f). 기준 커밋: `7a5d106fa569f877579634a262b1b7e9e3c2c20f`.

| 참고 경로 (`src/RainWorldDesktopPet/`) | 이 생성기에 반영한 원리 |
| --- | --- |
| `Graphics/SlugcatGraphics.cs` | 흉부/골반의 다른 보행 위상, 독립적인 머리 반응, 호흡과 불규칙한 눈 깜빡임 |
| `Graphics/ProceduralTail.cs` | 세그먼트 관성, 감쇠, 거리 제약, 바닥 접촉, 이동 상태에 따른 꼬리 반응 |
| `Graphics/SlugcatPose.cs` | 몸통·머리·팔·발·꼬리를 분리한 포즈 데이터와 착지 압축 |

원본 저장소를 변경하지 않는다. .NET/Windows 엔진을 이식하거나 게임 DLL·아틀라스·음원을 복사하지 않았다. 직접 작성한 경량 물리 모델과 SVG 실루엣으로 움직임 원리를 재해석한 팬 작업이며, 원작 스프라이트와 픽셀 단위로 동일한 렌더러는 아니다. 출처 및 원본 MIT 고지는 [UPSTREAM-NOTICE.txt](../tools/slugcat/UPSTREAM-NOTICE.txt)에 있다.

## 파일 구조

```text
.github/workflows/slugcat-animation.yml  # 테스트, 일일 생성, 출력만 커밋
 tools/slugcat/
   contributions.py                    # 공식 GraphQL → 검증된 365일 스냅샷
   motion.py                           # 행동 계획과 120 Hz 물리 계산
   render.py                           # 트랙 압축, 자체 포함 SVG 생성/검증
   generate.py                         # 실행 진입점, 원자적 파일 교체
   UPSTREAM-NOTICE.txt
 tests/test_slugcat.py                  # 네트워크 없는 회귀 테스트
 assets/slugcat/
   slugcat-light.svg
   slugcat-dark.svg
   slugcat-light-static.svg
   slugcat-dark-static.svg
   manifest.json                       # 날짜·데이터 출처·동선·해시·품질 정보
   contributions.json                  # 실제 API 조회 성공 뒤에만 생성되는 캐시
 README.md                             # 기존 본문 유지, 하단에 picture 추가
```

## 움직임

전체 루프는 36.0초다. Idle → Walk → 짧은 정지 → Walk → Inspect → Crouch → Hop → Land → Turn → 복귀 → Inspect → Turn → Idle로 이어진다. 중앙 구역의 실제 contribution 칸에 활동량 가중치를 주어 관심 대상을 고른다. 루프 길이와 화면 경계를 지키기 위해 관심 후보를 그래프 중앙부로 제한한다. 활동량이 높은 칸만 무조건 고르지는 않는다.

동선의 목표점은 부드럽게 연결하지만, 몸 자체의 자세를 고정 키프레임으로 복사하지 않는다. 골반·흉부·머리·팔은 서로 다른 강성과 감쇠로 적분한다. 발은 디딜 때 월드 좌표를 고정하고, 다음 발을 놓을 때만 들어 올린다. 꼬리는 7개 연결 세그먼트를 월드 좌표에서 계산하고, 두께가 줄어드는 연속 곡면으로 그려 마디의 틈이 보이지 않게 한다. 방향을 돌릴 때 전체 캐릭터를 한꺼번에 좌우 반전하지 않는다.

호흡, 작게 움직이는 시선, 불규칙한 눈 깜빡임, 보행과 별개의 미세 흔들림을 합성한다. 점프는 중력과 발사 속도로 계산하고, 출발 전 몸을 낮추며 착지 시 압축된다. 생성 날짜와 정상화된 데이터가 같으면 난수 시드와 결과도 같다.

120 Hz 고정 물리 계산에서 기본 24 fps로 포즈를 샘플링한다. 출력은 865개 표본(닫힘 표본 포함)을 그대로 프레임 그림으로 나열하지 않고, 오차 한도 내에서 트랙을 줄여 SVG `animate`/`animateTransform`에 저장한다. 브라우저가 그 사이를 보간하므로 24 fps는 표시 장치의 강제 프레임률이 아니다.

루프를 여러 번 예열하여 포즈가 주기적 상태에 수렴한 뒤 시작/끝 오차를 검사한다. 수렴하지 않으면 생성에 실패한다. 마지막 프레임으로 순간이동하거나 화면을 페이드해 경계를 숨기지 않는다. 각 SVG는 900,000바이트를 넘으면 실패한다.

## 실행

Python 3.13 표준 라이브러리만 사용한다. `pip install`이나 게임 설치가 필요 없다. 저장소 루트에서:

```sh
python -m compileall -q tools/slugcat tests/test_slugcat.py
python -m unittest discover -s tests -v
python -m tools.slugcat.generate --user joohyunjin09
```

마지막 명령은 기존 정상 캐시를 읽거나, 캐시가 없으면 명확히 표시된 레이아웃 미리보기를 생성한다. 실제 데이터를 갱신하려면 `GH_TOKEN` 또는 `GITHUB_TOKEN` 환경변수에 토큰을 전달하고:

```sh
python -m tools.slugcat.generate --user joohyunjin09 --fetch
```

토큰은 명령행 인자나 생성 파일에 넣지 않는다. Actions에서는 자동 제공되는 `github.token`을 사용한다. 로컬에서 토큰을 사용할 때도 셸 히스토리·로그·저장소에 노출하지 않는다.

고정 날짜/별도 폴더로 재생성할 수도 있다:

```sh
python -m tools.slugcat.generate --date 2026-09-12 --output /tmp/slugcat-preview
```

실제 스냅샷은 캐시의 날짜를 보존하므로 오래된 캐시를 오늘의 데이터라고 표시하지 않는다. 다른 사용자의 캐시, 미래 캐시, 누락/중복 날짜, 비정상 수치는 거부한다. API에서 돌아오는 주 단위 패딩 날짜는 요청한 365일 구간으로 잘라낸 뒤 검증한다.

## Actions

`White slugcat profile animation` 워크플로는 관련 소스의 main push, 수동 실행, 매일 `22:23 UTC`(한국 시간 다음 날 `07:23`)에 동작한다. PR에서는 테스트만 하고 게시하지 않는다.

1. 별도 읽기 전용 테스트 작업에서 컴파일과 회귀 테스트를 실행한다.
2. 통과하면 공식 GraphQL API로 contribution 데이터를 조회한다.
3. 네 가지 SVG를 모두 생성·검증한 뒤 캐시와 manifest를 기록한다.
4. 생성 파일을 7일 보관하는 Actions artifact로 남긴다.
5. 생성 경로에 변경이 있을 때만 `main`에 봇 커밋을 만든다. 기존 README와 다른 에셋에는 손대지 않는다.

쓰기 권한은 게시 작업의 `contents: write`에만 부여한다. 액션 버전은 검증한 전체 커밋 SHA로 고정했다. 강제 push를 하지 않으므로 다른 변경이 먼저 올라오면 충돌한 게시가 실패하고 새 변경을 덮어쓰지 않는다. 생성 커밋은 경로 필터와 `[skip ci]`로 자기 자신을 다시 실행하지 않는다.

GitHub의 예약 실행은 정확한 시각을 보장하지 않으며 혼잡 시 지연되거나 누락될 수 있다. 공개 저장소가 장기간 비활성 상태이면 예약 워크플로가 비활성화될 수도 있다. Actions 설정/브랜치 정책이 봇 push를 막으면 정책에 맞게 허용하거나, artifact를 받아 수동 반영한다. 이 생성기는 해당 정책을 우회하지 않는다.

API 장애는 최대 세 번의 제한된 재시도 후 정상 캐시로 대체한다. 캐시도 없으면 모든 칸이 비어 있는 `Layout preview / GitHub data not loaded`가 표시된다. 테스트용 가짜 활동 내역을 본인 데이터처럼 게시하지 않는다. 출처는 `manifest.json`의 `source`(`github`, `cache`, `layout`)로 확인한다. 렌더링/검증 실패 시 기존 정상 출력과 캐시를 보존한다.

## README 마크업

```html
<picture>
  <source media="(prefers-reduced-motion: reduce) and (prefers-color-scheme: dark)" srcset="./assets/slugcat/slugcat-dark-static.svg">
  <source media="(prefers-reduced-motion: reduce)" srcset="./assets/slugcat/slugcat-light-static.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/slugcat/slugcat-dark.svg">
  <img src="./assets/slugcat/slugcat-light.svg" alt="커밋 사이를 산책하는 흰색 슬러그캣 한 마리. 호흡하고, 눈을 깜빡이고, 걷고, 작은 점프를 합니다." width="100%">
</picture>
```

캔버스는 896×238, 외곽 배경은 투명하다. 라이트·다크 팔레트와 동작 줄이기 설정을 위한 정적 에셋을 제공한다. SVG 자체에도 reduced-motion 대체 장면이 있어 `<img>`로 직접 삽입해도 대응한다. 애니메이션 미지원 뷰어에서는 기본 포즈가 남는다. `prefers-color-scheme`은 브라우저에 노출된 색상 선호를 기준으로 하며, GitHub 사이트 설정과 OS 설정을 서로 다르게 강제한 모든 조합까지 보장하는 것은 아니다.

## 제약과 검증

GitHub의 실제 contribution DOM, 다른 README 요소의 위치, 방문자의 마우스/스크롤에 접근하지 않는다. 이미지 내부에서 그린 contribution 스냅샷 위를 걸을 뿐이며 native contribution 그래프를 수정하거나 그 위에 overlay를 얹는 기능은 아니다. 실제 활동 데이터의 갱신은 빌드 시점에만 이루어진다. 이미지 캐시로 새 에셋의 표시가 늦어질 수 있다.

회귀 테스트는 발 디딤, 꼬리 길이/바닥 접촉, 좌표 유효성, 루프 경계의 위치/속도, 물리와 출력 표본률 분리, 데이터 검증/오류 복구, 결정론, 트랙 압축, 안전한 SVG, 출력 크기/해시 등을 검사한다. 로컬 Chromium의 이미지 임베딩에서도 애니메이션 재생, 라이트/다크, reduced-motion의 정지, 모바일 폭을 확인했다. 이 로컬 테스트는 GitHub 서버의 이미지 프록시를 통한 실제 프로필 렌더링 테스트를 대신하지 않으며, 모든 브라우저를 검증했다는 의미도 아니다.

## 확장 지점

`motion.py`의 관심 대상 가중치와 행동 계획에서 활동량별 호기심·연속 활동 연출을 추가할 수 있다. 비·먹이·카르마 표시는 `render.py`에서 별도의 오프라인 트랙으로 확장한다. 다만 캐릭터 수는 한 마리로 유지하고, 본래 소개글보다 시선을 빼앗지 않도록 루프 시간·출력 크기·reduced-motion 검증을 함께 유지한다.

## 기술 문서

- [SVG 이미지 컨텍스트의 제약 (MDN)](https://developer.mozilla.org/en-US/docs/Web/SVG/Guides/SVG_as_an_image)
- [GitHub Actions 이벤트와 schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub GraphQL 문서](https://docs.github.com/en/graphql)
