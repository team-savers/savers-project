// Home (/). 서비스 소개 랜딩 — 일반 시민·보호자가 처음 만나는 화면.
//
// 이름 주의: 이 레포의 `Landing.tsx` 는 /a?t= 알림 수신 화면이다. 소개
// 랜딩과 이름이 겹치므로 이 파일은 Home 으로 둔다. App.tsx 의 HomeView()
// 스텁을 이것으로 교체하면 된다.
//
// 2026-08-25 재구성: 데스크톱·태블릿·모바일 반응형 랜딩으로 구성했다.
// 색상은 Home.css의 지역 CSS 변수로 한정해 Register/Join/Ops 등
// lib/tokens.ts를 사용하는 다른 화면에 영향을 주지 않는다.
//
// 재사용: useReveal 스크롤 등장 훅, REGISTER_URL 상수·경로,
// public/logo.png의 SAVERS 로고 asset, lib/tokens.ts의 ICON 스타일.
//
// 데이터 의존 없음: api / mocks 를 호출하지 않는 정적 화면이다. 그래서
// 로딩·실패 상태가 없고, 어떤 상황에서도 빈 화면이 되지 않는다.

import { Fragment, useEffect, type ReactElement, type ReactNode } from 'react'
import { ICON } from '../lib/tokens'
import heroIllustration from '../assets/home.webp'
import './Home.css'

// ---------------------------------------------------------------------------
// 스크롤 등장 효과
//
// prefers-reduced-motion 이면 옵저버를 아예 만들지 않고 처음부터 보이게
// 둔다. 광과민성·어지럼 대응은 애니메이션을 "느리게"가 아니라 "없이"다.
// ---------------------------------------------------------------------------
function useReveal(): void {
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    if (!('IntersectionObserver' in window)) return

    const els = Array.from(
      document.querySelectorAll<HTMLElement>('[data-reveal]'),
    )
    if (els.length === 0) return

    els.forEach((el) => {
      el.style.opacity = '0'
      el.style.transform = 'translateY(16px)'
      el.style.transition =
        'opacity .5s cubic-bezier(.22,.7,.3,1), transform .5s cubic-bezier(.22,.7,.3,1)'
    })

    let seen = 0
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (!e.isIntersecting) return
          const target = e.target as HTMLElement
          const delay = Math.min(seen, 3) * 60
          seen += 1
          window.setTimeout(() => {
            target.style.opacity = '1'
            target.style.transform = 'none'
          }, delay)
          io.unobserve(target)
        })
      },
      { threshold: 0.12, rootMargin: '0px 0px -8% 0px' },
    )
    els.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [])
}

const REGISTER_URL = '/register'

// ---------------------------------------------------------------------------
// 작은 조각들
// ---------------------------------------------------------------------------

function FeatureIcon({ children }: { children: ReactNode }) {
  return (
    <div
      aria-hidden="true"
      style={{
        width: '52px',
        height: '52px',
        borderRadius: '50%',
        background: 'var(--h-bg-soft)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flex: 'none',
        color: 'var(--h-blue)',
      }}
    >
      {children}
    </div>
  )
}

interface FeatureCardProps {
  icon: ReactElement
  title: string
  body: string
}

interface PromiseCardProps {
  title: string
  body: string
}

function PromiseCard({ title, body }: PromiseCardProps) {
  return (
    <div className="home-promise-card" data-reveal>
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        style={{ ...ICON, width: 24, height: 24 }}
      >
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
        <path d="m9 11 2 2 4-4" />
      </svg>
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
  )
}

function FeatureCard({ icon, title, body }: FeatureCardProps) {
  return (
    <div
      data-reveal
      style={{
        background: 'var(--h-card)',
        border: '1px solid var(--h-line)',
        borderRadius: '16px',
        padding: '24px 20px',
      }}
    >
      <FeatureIcon>{icon}</FeatureIcon>
      <div
        style={{
          fontSize: '18px',
          fontWeight: 700,
          marginTop: '16px',
          marginBottom: '8px',
        }}
      >
        {title}
      </div>
      <div style={{ fontSize: '15px', lineHeight: 1.6, color: 'var(--h-text-muted)' }}>
        {body}
      </div>
    </div>
  )
}

interface StepItemProps {
  n: number
  title: string
  body: string
  icon: ReactElement
  tone?: 'blue' | 'red'
}

function StepItem({ n, title, body, icon, tone = 'blue' }: StepItemProps) {
  return (
    <div className="home-steps-item" data-reveal>
      <div
        aria-hidden="true"
        style={{
          width: '56px',
          height: '56px',
          borderRadius: '50%',
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flex: 'none',
          background: tone === 'red' ? 'rgba(229,72,63,.1)' : 'var(--h-bg-soft)',
          color: tone === 'red' ? 'var(--h-red)' : 'var(--h-blue)',
        }}
      >
        {icon}
      </div>
      <div style={{ marginTop: '14px' }}>
        <span style={{ color: 'var(--h-orange)', fontWeight: 800, fontSize: '16px' }}>
          {n}
        </span>{' '}
        <span style={{ fontWeight: 700, fontSize: '16px' }}>{title}</span>
        <div
          style={{
            fontSize: '14px',
            lineHeight: 1.6,
            color: 'var(--h-text-muted)',
            marginTop: '6px',
          }}
        >
          {body}
        </div>
      </div>
    </div>
  )
}

function StepArrow() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="home-steps-arrow"
      style={{ ...ICON, width: 20, height: 20 }}
    >
      <path d="M5 12h13" />
      <path d="m13 6 6 6-6 6" />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// 데이터
// ---------------------------------------------------------------------------

const FEATURES: FeatureCardProps[] = [
  {
    title: '빠른 재난 알림',
    body: '재난 상황에 필요한 안내를 빠르게 전달합니다.',
    icon: (
      <svg viewBox="0 0 24 24" style={{ ...ICON, width: 24, height: 24 }}>
        <path d="M12 3a6 6 0 0 0-6 6v3.6L4 16h16l-2-3.4V9a6 6 0 0 0-6-6Z" />
        <path d="M9.5 19a2.5 2.5 0 0 0 5 0" />
      </svg>
    ),
  },
  {
    title: '보호자 안전 확인',
    body: '사용자의 행동 기록을 바탕으로 보호자가 현재 상황을 확인할 수 있습니다.',
    icon: (
      <svg viewBox="0 0 24 24" style={{ ...ICON, width: 24, height: 24 }}>
        <circle cx="8.5" cy="8" r="3.2" />
        <path d="M2.5 20c0-3.3 2.7-5.6 6-5.6s6 2.3 6 5.6" />
        <circle cx="17" cy="9" r="2.4" />
        <path d="M14.7 20c.3-2.4 1.9-4.2 4.3-4.5" />
      </svg>
    ),
  },
  {
    title: '상황별 대피 안내',
    body: '등록 정보와 주변 대피소 조건을 바탕으로 상황에 맞는 안전 행동을 안내합니다.',
    icon: (
      <svg viewBox="0 0 24 24" style={{ ...ICON, width: 24, height: 24 }}>
        <path d="M12 21s7-6.8 7-12.4A7 7 0 0 0 5 8.6C5 14.2 12 21 12 21Z" />
        <circle cx="12" cy="8.6" r="2.6" />
      </svg>
    ),
  },
  {
    title: '안전한 연락 연결',
    body: '필요할 때 119 등 긴급 연락으로 빠르게 연결합니다.',
    icon: (
      <svg viewBox="0 0 24 24" style={{ ...ICON, width: 24, height: 24 }}>
        <path d="M6.6 10.8a15.9 15.9 0 0 0 6.6 6.6l2.2-2.2c.3-.3.8-.4 1.3-.3 1.1.4 2.4.6 3.6.6.8 0 1.4.6 1.4 1.4V21a1.4 1.4 0 0 1-1.4 1.4C10.6 22.4 1.6 13.4 1.6 3.7A1.4 1.4 0 0 1 3 2.3h3.7c.8 0 1.4.6 1.4 1.4 0 1.3.2 2.5.6 3.6.1.5 0 1-.3 1.3L6.6 10.8Z" />
      </svg>
    ),
  },
]

const STEPS: (Omit<StepItemProps, 'n'> & { n: number })[] = [
  {
    n: 1,
    title: '사전정보 등록',
    body: '기본 정보와 보호자 정보를 미리 등록합니다.',
    icon: (
      <svg viewBox="0 0 24 24" style={{ ...ICON, width: 24, height: 24 }}>
        <circle cx="12" cy="8" r="3.6" />
        <path d="M4.5 20c0-4 3.3-6.6 7.5-6.6s7.5 2.6 7.5 6.6" />
      </svg>
    ),
  },
  {
    n: 2,
    title: '재난 알림 수신',
    body: '재난 발생 시 필요한 행동 안내를 확인합니다.',
    tone: 'red',
    icon: (
      <svg viewBox="0 0 24 24" style={{ ...ICON, width: 24, height: 24 }}>
        <path d="M12 3a6 6 0 0 0-6 6v3.6L4 16h16l-2-3.4V9a6 6 0 0 0-6-6Z" />
        <path d="M9.5 19a2.5 2.5 0 0 0 5 0" />
      </svg>
    ),
  },
  {
    n: 3,
    title: '행동 선택',
    body: '도움 요청 또는 직접 대피 등 현재 상황에 맞는 행동을 선택합니다.',
    icon: (
      <svg viewBox="0 0 24 24" style={{ ...ICON, width: 24, height: 24 }}>
        <path d="M9 11.5 11 13.5 15.5 8" />
        <circle cx="12" cy="12" r="9" />
      </svg>
    ),
  },
  {
    n: 4,
    title: '안전 진행 확인',
    body: '대피 과정의 행동 기록이 안전 확인에 활용됩니다.',
    icon: (
      <svg viewBox="0 0 24 24" style={{ ...ICON, width: 24, height: 24 }}>
        <path d="M6 4h9l3 3v13H6Z" />
        <path d="M9 11h6M9 15h6" />
        <circle cx="17.5" cy="17.5" r="3.2" />
        <path d="m16.2 17.5 1 1 1.8-1.9" />
      </svg>
    ),
  },
  {
    n: 5,
    title: '보호자 확인 및 지원',
    body: '필요한 경우 보호자가 현재 기록을 확인하고 추가 대응을 할 수 있습니다.',
    icon: (
      <svg viewBox="0 0 24 24" style={{ ...ICON, width: 24, height: 24 }}>
        <path d="M6.6 10.8a15.9 15.9 0 0 0 6.6 6.6l2.2-2.2c.3-.3.8-.4 1.3-.3 1.1.4 2.4.6 3.6.6.8 0 1.4.6 1.4 1.4V21a1.4 1.4 0 0 1-1.4 1.4C10.6 22.4 1.6 13.4 1.6 3.7A1.4 1.4 0 0 1 3 2.3h3.7c.8 0 1.4.6 1.4 1.4 0 1.3.2 2.5.6 3.6.1.5 0 1-.3 1.3L6.6 10.8Z" />
      </svg>
    ),
  },
]

// ---------------------------------------------------------------------------
// 조각: header / hero / footer
// ---------------------------------------------------------------------------

function Header() {
  return (
    <header className="home-header">
      <a href="#hero" className="home-header-brand">
        <img
          src="/logo.png"
          alt="SAVERS 로고"
          style={{ width: '34px', height: '34px', display: 'block', objectFit: 'contain' }}
        />
        <span style={{ lineHeight: 1.15 }}>
          <span style={{ display: 'block', fontSize: '20px', fontWeight: 800, color: 'var(--h-blue)' }}>
            SAVERS
          </span>
          <span style={{ display: 'block', fontSize: '12px', color: 'var(--h-text-muted)' }}>
            안전한 연결, 함께 지키는 삶
          </span>
        </span>
      </a>

      {/* 아직 실제 콘텐츠가 없는 메뉴(안전 정보/고객센터)는 새 route를
          만들지 않고 텍스트로만 둔다 — 실제 section이 있는 항목만 anchor. */}
      <nav className="home-header-nav" aria-label="주요 메뉴">
        <a href="#hero">서비스 소개</a>
        <a href="#how-it-works">이용 방법</a>
        <a href="/ops">담당자 등록</a>
        <span>안전 정보</span>
        <span>고객센터</span>
      </nav>

      <a
        href={REGISTER_URL}
        style={{
          background: 'var(--h-blue)',
          color: '#fff',
          borderRadius: '10px',
          padding: '11px 18px',
          fontSize: '15px',
          fontWeight: 700,
          textDecoration: 'none',
          whiteSpace: 'nowrap',
        }}
      >
        사전정보 등록하기
      </a>
    </header>
  )
}

function Hero() {
  return (
    <section id="hero" className="home-hero">
      <div className="home-hero-grid">
        <div>
          <div
            data-reveal
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              border: '1.5px solid var(--h-orange)',
              borderRadius: '999px',
              padding: '7px 16px',
              marginBottom: '22px',
            }}
          >
            <svg viewBox="0 0 24 24" style={{ ...ICON, width: 16, height: 16, color: 'var(--h-orange)' }}>
              <path d="M12 21s7-6.8 7-12.4A7 7 0 0 0 5 8.6C5 14.2 12 21 12 21Z" />
              <circle cx="12" cy="8.6" r="2.6" />
            </svg>
            <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--h-text)' }}>
              사람과 기술을 위한 재난 안전 서비스
            </span>
          </div>

          <h1
            data-reveal
            style={{
              fontSize: 'clamp(32px, 4.4vw, 50px)',
              fontWeight: 800,
              lineHeight: 1.28,
              letterSpacing: '-.02em',
              margin: '0 0 20px',
              textWrap: 'pretty',
            }}
          >
            재난이 와도,
            <br />
            함께라서 <span style={{ color: 'var(--h-orange)' }}>안심</span>입니다
          </h1>

          <p
            data-reveal
            style={{
              fontSize: '18px',
              lineHeight: 1.7,
              color: 'var(--h-text-muted)',
              margin: '0 0 30px',
              maxWidth: '480px',
              textWrap: 'pretty',
            }}
          >
            SAVERS는 재난 상황에서 사용자와 보호자를 연결해 신속한 알림과
            안전 확인을 돕습니다.
          </p>

          <div className="home-hero-ctas" data-reveal>
            <a
              href={REGISTER_URL}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'var(--h-orange)',
                color: '#fff',
                borderRadius: '12px',
                padding: '16px 26px',
                fontSize: '16px',
                fontWeight: 700,
                textDecoration: 'none',
                minHeight: '52px',
              }}
            >
              사전정보 등록하기
            </a>
            <a
              href="#features"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'var(--h-card)',
                color: 'var(--h-text)',
                border: '1.5px solid var(--h-line)',
                borderRadius: '12px',
                padding: '16px 26px',
                fontSize: '16px',
                fontWeight: 700,
                textDecoration: 'none',
                minHeight: '52px',
              }}
            >
              서비스 알아보기
            </a>
          </div>
        </div>

        <img
          data-reveal
          src={heroIllustration}
          alt="스마트폰을 함께 보는 어르신과 곁에서 살펴봐주는 보호자"
          className="home-hero-illustration"
        />
      </div>
    </section>
  )
}

function Footer() {
  return (
    <footer className="home-footer">
      <div className="home-footer-grid">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
            <img
              src="/logo.png"
              alt="SAVERS 로고"
              style={{ width: '24px', height: '24px', display: 'block', objectFit: 'contain' }}
            />
            <span style={{ fontSize: '16px', fontWeight: 800, color: 'var(--h-blue)' }}>SAVERS</span>
          </div>
          <div style={{ fontSize: '13px', color: 'var(--h-text-muted)' }}>
            © 2026 SAVERS. All rights reserved.
          </div>
        </div>

        {/* 실제로 이동 가능한 항목만 <a>, 아직 콘텐츠가 없는 항목은 <span> —
            가짜 링크를 만들지 않는다. */}
        <div className="home-footer-links">
          <div>
            <div style={{ fontSize: '14px', fontWeight: 700, marginBottom: '6px' }}>서비스</div>
            <a href="#hero">서비스 소개</a>
            <a href="#how-it-works">이용 방법</a>
            <a href="/ops">복지관·지자체 담당자 등록</a>
          </div>
          <div>
            <div style={{ fontSize: '14px', fontWeight: 700, marginBottom: '6px' }}>이용 안내</div>
            <span>재난 안전 정보</span>
            <span>자주 묻는 질문</span>
          </div>
          <div>
            <div style={{ fontSize: '14px', fontWeight: 700, marginBottom: '6px' }}>고객센터</div>
            <span>공지사항</span>
            <span>문의하기</span>
          </div>
          <div>
            <div style={{ fontSize: '14px', fontWeight: 700, marginBottom: '6px' }}>정책</div>
            <span>개인정보처리방침</span>
            <span>이용약관</span>
          </div>
        </div>
      </div>
    </footer>
  )
}

// ---------------------------------------------------------------------------
// Home
// ---------------------------------------------------------------------------
export function Home(): React.ReactElement {
  useReveal()

  return (
    <div className="home-page">
      <Header />
      <Hero />

      {/* ===================== 핵심 기능 ===================== */}
      <section id="features" className="home-features">
        <h2 data-reveal>핵심 기능</h2>
        <div className="home-features-grid">
          {FEATURES.map((f) => (
            <FeatureCard key={f.title} {...f} />
          ))}
        </div>
      </section>

      {/* ===================== 서비스 원칙 ===================== */}
      <section className="home-promises" aria-labelledby="promises-title">
        <h2 id="promises-title" data-reveal>
          안심하고 사용할 수 있도록 약속합니다
        </h2>
        <div className="home-promises-grid">
          <PromiseCard
            title="위치는 딱 한 번만 확인해요"
            body="알림을 열 때 현재 위치를 1회만 확인하고 저장하지 않습니다."
          />
          <PromiseCard
            title="설치할 앱이 없어요"
            body="앱스토어에서 별도 앱을 설치하지 않고 알림의 링크로 바로 이용합니다."
          />
          <PromiseCard
            title="공식 근거 안에서 안내해요"
            body="근거를 찾지 못하면 답하지 않으며, 긴급재난문자를 대체하지 않고 행동 안내를 보완합니다."
          />
        </div>
      </section>

      {/* ===================== 이용 방법 ===================== */}
      <section id="how-it-works" className="home-steps">
        <h2
          data-reveal
          style={{
            fontSize: '26px',
            fontWeight: 800,
            margin: '0 0 32px',
            textAlign: 'center',
          }}
        >
          SAVERS는 이렇게 사용돼요
        </h2>
        <div className="home-steps-row">
          {STEPS.map((s, i) => (
            <Fragment key={s.n}>
              <StepItem {...s} />
              {i < STEPS.length - 1 && <StepArrow />}
            </Fragment>
          ))}
        </div>
      </section>

      <Footer />
    </div>
  )
}
