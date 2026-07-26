# AI 엔진 단독 이미지 — "독립 배포 가능한 모듈"임을 증명하는 산출물입니다.
# 빌드 컨텍스트는 이 디렉토리(apps/ai-engine)입니다. backend 소스를 참조하지 마세요.
#   docker build -t savers-ai-engine:dev apps/ai-engine
#   docker run --rm -p 8100:8100 --env-file infra/.env savers-ai-engine:dev
#
# ⚠️ CPU 전용입니다 (ADR-0003). 임베딩/생성은 외부 API(HyperCLOVA X)를 호출하므로
#    GPU 베이스 이미지로 바꾸지 마세요 — 단일 VM 예산을 초과합니다.
FROM python:3.12-slim

# 파이썬 런타임 위생: .pyc 미생성, 로그 버퍼링 해제(컨테이너 로그 지연 방지)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성 레이어를 소스와 분리해 캐시 적중률을 높인다.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# 비루트 실행 — 단일 VM에 여러 서비스가 뜨므로 권한 격리를 유지한다.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8100
CMD ["uvicorn", "ai_engine.service:app", "--host", "0.0.0.0", "--port", "8100"]
