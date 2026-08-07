"""시드 데이터에 대한 유일한 참조점. backend_core/registry.py의 seed_registry·DEMO_DONG_CODE와
짝이지만, HTTP 전용 규약 때문에 import할 수 없어 값을 여기 한 번만 적어 둔다. 시드가 바뀌면
고칠 곳은 이 두 상수뿐 — 테스트 파일마다 복사해 두면 한쪽만 고쳐진 채 "매칭 실패"로만
보이는 실패가 남고, 원인이 시드 변경이라는 걸 알기 어렵다.

conftest.py가 아니라 별도 모듈인 이유: pytest는 conftest.py를 모듈명 `conftest`로
`sys.modules`에 올리는데, 이 레포에는 conftest.py가 3개(e2e/, apps/backend/tests/,
apps/ai-engine/tests/) 있어 한 세션이 둘 이상을 수집하면 먼저 올라간 쪽이 이름을 차지하고
`from conftest import ...`가 나머지 쪽에서 ImportError로 죽는다 (PR #66 리뷰).
"""

# p001 = 김순자. stairs_ok=False + 보호자 등록 — 가장 취약한 프로필이면서 보호자 연결까지
# 가진 유일한 시드 주민이라 정상 경로와 최악 경로 양쪽의 대상이다.
WORST_CASE_USER_ID = "p001"
# 데모 특보가 덮는 시드 행정동(서원동). 대피소 픽스처가 존재하는 유일한 행정동이다.
SEED_DONG_CODE = "1162064500"
