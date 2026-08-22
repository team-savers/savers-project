// Home (/). 서비스 소개 랜딩 — 일반 시민·보호자가 처음 만나는 화면.
//
// 이름 주의: 이 레포의 `Landing.tsx` 는 /a?t= 알림 수신 화면이다. 소개
// 랜딩과 이름이 겹치므로 이 파일은 Home 으로 둔다. App.tsx 의 HomeView()
// 스텁을 이것으로 교체하면 된다.
//
// 설계 제약 (기획서 · ADR-0004):
//   - 402px 모바일 전용. 반응형 데스크톱 레이아웃을 만들지 않는다.
//   - 상시 바텀탭 네비게이션 없음. 단일 스크롤 흐름 + 하단 상시 CTA 하나.
//   - CTA 는 /ops(대리등록)로 간다.
//
// 데이터 의존 없음: api / mocks 를 호출하지 않는 정적 화면이다. 그래서
// 로딩·실패 상태가 없고, 어떤 상황에서도 빈 화면이 되지 않는다.
//
// 카피 원칙: "부모님은 그 문자를 읽고 움직이실 수 있을까요?" 같은 효심
// 호소는 의도적으로 버렸다. 감정을 짜내지 않고 사실만 말한다 —
// "문자는 도착했습니다. 아무도 움직이지 않았습니다."

import { useEffect, useRef, useState } from 'react'
import { C, FONT_MONO, SHADOW_CARD } from '../lib/tokens'

// 이미지는 designs/assets/ 의 파일을 src/assets/ 로 옮긴 뒤 import 한다.
// import 로 받으면 Vite 가 해시 파일명을 붙여 캐시 무효화를 처리한다.
import heroFamily from '../assets/lp-hero-b.png'
import basement from '../assets/lp-basement.png'
import registerHint from '../assets/lp-hero-a.png'
import logoLight from '../assets/logo-mark-light.png'

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
        'opacity .62s cubic-bezier(.22,.7,.3,1), transform .62s cubic-bezier(.22,.7,.3,1)'
    })

    // 스태거는 "화면에 들어온 순서"로 준다. DOM 순서로 주면 스크롤을 빨리
    // 내렸을 때 이미 지나간 요소가 뒤늦게 나타난다.
    let seen = 0
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (!e.isIntersecting) return
          const target = e.target as HTMLElement
          const delay = Math.min(seen, 3) * 70
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

// ---------------------------------------------------------------------------
// 작은 조각들
// ---------------------------------------------------------------------------
const ICON_BASE = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  flex: 'none',
}

function SectionLabel({ children }: { children: string }) {
  return (
    <div
      data-reveal
      style={{
        fontFamily: FONT_MONO,
        fontSize: '12px',
        fontWeight: 600,
        letterSpacing: '.16em',
        color: C.tealText,
        marginBottom: '12px',
      }}
    >
      {children}
    </div>
  )
}

interface ProblemCardProps {
  title: string
  body: string
  icon: React.ReactElement
}

function ProblemCard({ title, body, icon }: ProblemCardProps) {
  return (
    <div
      data-reveal
      style={{
        background: C.white,
        borderRadius: '18px',
        padding: '19px 20px',
        display: 'flex',
        gap: '15px',
        alignItems: 'flex-start',
        boxShadow: SHADOW_CARD,
      }}
    >
      <div
        style={{
          width: '42px',
          height: '42px',
          borderRadius: '13px',
          background: C.tealBg,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flex: 'none',
          color: C.tealText,
        }}
      >
        {icon}
      </div>
      <div>
        <div
          style={{
            fontSize: '17px',
            fontWeight: 700,
            color: C.navy,
            marginBottom: '4px',
          }}
        >
          {title}
        </div>
        <div style={{ fontSize: '16px', lineHeight: 1.6, color: C.body }}>
          {body}
        </div>
      </div>
    </div>
  )
}

interface StepCardProps {
  n: string
  title: string
  children: React.ReactNode
  accent?: boolean
}

function StepCard({ n, title, children, accent = false }: StepCardProps) {
  return (
    <div
      data-reveal
      style={{
        background: C.white,
        borderRadius: '20px',
        padding: '22px',
        boxShadow: SHADOW_CARD,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          marginBottom: '14px',
        }}
      >
        <span
          style={{
            width: '34px',
            height: '34px',
            borderRadius: '11px',
            background: accent ? C.teal : C.navy,
            color: C.white,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: FONT_MONO,
            fontSize: '15px',
            fontWeight: 600,
            flex: 'none',
          }}
        >
          {n}
        </span>
        <span
          style={{
            fontSize: '19px',
            fontWeight: 800,
            color: C.navy,
            letterSpacing: '-.02em',
          }}
        >
          {title}
        </span>
      </div>
      <div
        style={{
          fontSize: '17px',
          lineHeight: 1.66,
          color: C.body,
          textWrap: 'pretty',
        }}
      >
        {children}
      </div>
    </div>
  )
}

interface PromiseCardProps {
  title: string
  body: string
  icon: React.ReactElement
}

function PromiseCard({ title, body, icon }: PromiseCardProps) {
  return (
    <div
      data-reveal
      style={{
        background: 'rgba(255,255,255,.07)',
        border: '1px solid rgba(255,255,255,.13)',
        borderRadius: '18px',
        padding: '20px',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '11px',
          marginBottom: '11px',
        }}
      >
        <div
          style={{
            width: '38px',
            height: '38px',
            borderRadius: '12px',
            background: 'rgba(95,201,174,.2)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flex: 'none',
            color: C.mint,
          }}
        >
          {icon}
        </div>
        <span
          style={{
            fontSize: '18px',
            fontWeight: 800,
            letterSpacing: '-.02em',
          }}
        >
          {title}
        </span>
      </div>
      <div
        style={{
          fontSize: '16px',
          lineHeight: 1.66,
          color: 'rgba(255,255,255,.74)',
        }}
      >
        {body}
      </div>
    </div>
  )
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div
      style={{
        flex: 1,
        background: C.white,
        borderRadius: '16px',
        padding: '17px 14px',
        textAlign: 'center',
        boxShadow: SHADOW_CARD,
      }}
    >
      <div
        style={{
          fontSize: '22px',
          fontWeight: 800,
          color: C.tealText,
          letterSpacing: '-.02em',
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: '13.5px', color: C.body, marginTop: '4px' }}>
        {label}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Home
// ---------------------------------------------------------------------------
const REGISTER_URL = '/register'

export function Home(): React.ReactElement {
  useReveal()

  // 하단 상시 CTA는 히어로 CTA가 화면에서 사라진 뒤에만 띄운다. 둘이 동시에
  // 보이면 같은 버튼이 두 개 있는 것처럼 읽힌다.
  const heroCtaRef = useRef<HTMLAnchorElement | null>(null)
  const [showStickyCta, setShowStickyCta] = useState(false)

  useEffect(() => {
    const el = heroCtaRef.current
    if (el === null) return
    if (!('IntersectionObserver' in window)) {
      setShowStickyCta(true)
      return
    }
    const io = new IntersectionObserver(
      (entries) => setShowStickyCta(!entries[0].isIntersecting),
      { threshold: 0 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])

  return (
    <main
      style={{
        width: '100%',
        maxWidth: '402px',
        margin: '0 auto',
        background: C.bg,
        // 한글은 단어 중간에서 끊지 않는다. 이게 없으면 "저장하지 않습니
        // 다." 처럼 어색하게 잘린다.
        wordBreak: 'keep-all',
        overflowWrap: 'break-word',
        position: 'relative',
      }}
    >
      {/* ===================== HERO ===================== */}
      <section
        style={{
          background: C.navy,
          color: C.white,
          padding: '22px 24px 34px',
          borderRadius: '0 0 28px 28px',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            right: '-70px',
            top: '-90px',
            width: '220px',
            height: '220px',
            borderRadius: '50%',
            background: C.mint,
            opacity: 0.16,
            filter: 'blur(50px)',
          }}
        />

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            position: 'relative',
            marginBottom: '34px',
          }}
        >
          <img
            src={logoLight}
            alt=""
            style={{
              width: '26px',
              height: '26px',
              display: 'block',
              objectFit: 'contain',
            }}
          />
          <span
            style={{
              fontSize: '19px',
              fontWeight: 800,
              letterSpacing: '-.01em',
            }}
          >
            SAVERS
          </span>
          <span
            style={{
              marginLeft: 'auto',
              fontFamily: FONT_MONO,
              fontSize: '11px',
              letterSpacing: '.08em',
              color: 'rgba(255,255,255,.55)',
            }}
          >
            세이버스
          </span>
        </div>

        <div style={{ position: 'relative' }}>
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '7px',
              background: 'rgba(95,201,174,.16)',
              border: '1px solid rgba(95,201,174,.4)',
              borderRadius: '20px',
              padding: '7px 13px',
              marginBottom: '20px',
            }}
          >
            <span
              style={{
                width: '7px',
                height: '7px',
                borderRadius: '50%',
                background: C.mint,
              }}
            />
            <span
              style={{
                fontSize: '13px',
                fontWeight: 600,
                color: C.mintPale,
              }}
            >
              재난 취약계층 맞춤 대피 안내
            </span>
          </div>

          <h1
            style={{
              fontSize: '33px',
              fontWeight: 800,
              lineHeight: 1.32,
              letterSpacing: '-.03em',
              margin: '0 0 18px',
              textWrap: 'pretty',
            }}
          >
            문자는 도착했습니다.
            <br />
            아무도 움직이지 않았습니다.
          </h1>

          <p
            style={{
              fontSize: '18px',
              lineHeight: 1.66,
              color: 'rgba(255,255,255,.76)',
              margin: '0 0 26px',
              textWrap: 'pretty',
            }}
          >
            세이버스는 재난이 닥쳤을 때 지금 계신 위치를 확인하고,{' '}
            <b style={{ color: C.white }}>해야 할 행동 딱 하나</b>를 알려드립니다.
            앱 설치도, 복잡한 설정도 없습니다.
          </p>

          <img
            src={heroFamily}
            alt="비 오는 도시 위 보호막 아래 함께 서 있는 3세대 가족"
            style={{
              width: '100%',
              display: 'block',
              borderRadius: '22px',
              marginBottom: '26px',
            }}
          />

          <a
            ref={heroCtaRef}
            href={REGISTER_URL}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '9px',
              background: C.teal,
              color: C.white,
              borderRadius: '16px',
              padding: '19px',
              fontSize: '18px',
              fontWeight: 800,
              letterSpacing: '-.01em',
              textDecoration: 'none',
              minHeight: '56px',
            }}
          >
            내 가족 등록해주기
            <svg viewBox="0 0 24 24" style={{ ...ICON_BASE, width: 19, height: 19 }}>
              <path d="m9 18 6-6-6-6" />
            </svg>
          </a>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              marginTop: '16px',
              fontSize: '13.5px',
              color: 'rgba(255,255,255,.6)',
            }}
          >
            <svg
              viewBox="0 0 24 24"
              style={{ ...ICON_BASE, width: 15, height: 15, color: C.mint }}
            >
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
              <path d="m9 11 2 2 4-4" />
            </svg>
            행정안전부 국민행동요령 기반 · 무료
          </div>
        </div>
      </section>

      {/* ===================== 01 문제 ===================== */}
      <section style={{ padding: '38px 24px 44px' }}>
        <SectionLabel>01 &nbsp;왜 필요한가요</SectionLabel>
        <h2
          data-reveal
          style={{
            fontSize: '27px',
            fontWeight: 800,
            color: C.navy,
            lineHeight: 1.38,
            letterSpacing: '-.025em',
            margin: '0 0 18px',
            textWrap: 'pretty',
          }}
        >
          두 번의 여름,
          <br />
          같은 일이
          <br />
          반복됐습니다.
        </h2>
        <p
          data-reveal
          style={{
            fontSize: '18px',
            lineHeight: 1.7,
            color: C.body,
            margin: '0 0 24px',
            textWrap: 'pretty',
          }}
        >
          2022년 여름 관악구 신림동, 2023년 청주 오송. 긴급재난문자는 정상적으로
          발송됐습니다. 그런데도 반지하에서, 지하차도에서 사람들은 끝내 나오지
          못했습니다.
        </p>

        <img
          data-reveal
          src={basement}
          alt="비 오는 밤 반지하 집과 위층으로 향하는 계단"
          style={{
            width: '100%',
            display: 'block',
            borderRadius: '20px',
            marginBottom: '26px',
          }}
        />

        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
            marginBottom: '26px',
          }}
        >
          <ProblemCard
            title="동네 전체에 똑같은 문자"
            body="“내가 지금 어디로 가야 하는지”는 어디에도 없습니다."
            icon={
              <svg viewBox="0 0 24 24" style={{ ...ICON_BASE, width: 21, height: 21 }}>
                <path d="m3 11 18-5v12L3 14v-3z" />
                <path d="M11.6 16.8a3 3 0 1 1-5.8-1.6" />
              </svg>
            }
          />
          <ProblemCard
            title="읽고 판단할 시간이 없습니다"
            body="‘저지대 침수에 유의’가 무슨 뜻인지 생각할 겨를이 없습니다."
            icon={
              <svg viewBox="0 0 24 24" style={{ ...ICON_BASE, width: 21, height: 21 }}>
                <circle cx="12" cy="12" r="9" />
                <path d="M12 7v5l3.5 2" />
              </svg>
            }
          />
          <ProblemCard
            title="어르신은 몸도 느립니다"
            body="알아도 늦습니다. 그래서 더 일찍, 더 짧게 알려드려야 합니다."
            icon={
              <svg viewBox="0 0 24 24" style={{ ...ICON_BASE, width: 21, height: 21 }}>
                <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
            }
          />
        </div>

        <div
          data-reveal
          style={{
            background: C.navy,
            borderRadius: '20px',
            padding: '24px',
            color: C.white,
          }}
        >
          <div
            style={{
              fontSize: '20px',
              fontWeight: 800,
              lineHeight: 1.5,
              letterSpacing: '-.02em',
              textWrap: 'pretty',
            }}
          >
            부족한 건 정보가 아니라,
            <br />
            <span style={{ color: C.mint }}>정보를 행동으로 바꾸는 일</span>
            이었습니다.
          </div>
        </div>
      </section>

      {/* ===================== 02 Before / After ===================== */}
      <section style={{ background: C.white, padding: '44px 24px' }}>
        <SectionLabel>02 &nbsp;무엇이 다른가요</SectionLabel>
        <h2
          data-reveal
          style={{
            fontSize: '27px',
            fontWeight: 800,
            color: C.navy,
            lineHeight: 1.38,
            letterSpacing: '-.025em',
            margin: '0 0 24px',
          }}
        >
          같은 상황,
          <br />
          다른 안내
        </h2>

        <div
          data-reveal
          style={{
            background: C.greyBg,
            borderRadius: '18px',
            padding: '20px',
            marginBottom: '14px',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              marginBottom: '14px',
            }}
          >
            <span
              style={{
                fontFamily: FONT_MONO,
                fontSize: '11px',
                fontWeight: 600,
                letterSpacing: '.1em',
                color: C.tertiary,
              }}
            >
              BEFORE
            </span>
            <span
              style={{ fontSize: '13px', fontWeight: 600, color: C.tertiary }}
            >
              긴급재난문자
            </span>
          </div>
          <div
            style={{
              background: C.white,
              borderRadius: '14px',
              padding: '17px',
              fontSize: '16px',
              lineHeight: 1.66,
              color: C.body,
            }}
          >
            [관악구] 오늘 18시 호우경보 발효. 하천 및 저지대 침수에 유의하시고
            안전한 곳으로 대피 바랍니다.
          </div>
          <div
            style={{ fontSize: '14px', color: C.tertiary, marginTop: '12px' }}
          >
            → 어디로, 어떻게 가야 하는지는 없습니다.
          </div>
        </div>

        <div
          data-reveal
          style={{
            background: C.navy,
            borderRadius: '18px',
            padding: '20px',
            color: C.white,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              marginBottom: '14px',
            }}
          >
            <span
              style={{
                fontFamily: FONT_MONO,
                fontSize: '11px',
                fontWeight: 600,
                letterSpacing: '.1em',
                color: C.mint,
              }}
            >
              AFTER
            </span>
            <span
              style={{ fontSize: '13px', fontWeight: 600, color: C.mintPale }}
            >
              세이버스
            </span>
          </div>

          <div
            style={{
              background: 'rgba(255,255,255,.09)',
              borderRadius: '14px',
              padding: '17px',
              marginBottom: '12px',
            }}
          >
            <div style={{ fontSize: '17px', lineHeight: 1.62, fontWeight: 600 }}>
              길동님, 지금 계신 신림동 반지하는 물이 들어올 수 있어요.
            </div>
            <div
              style={{
                fontSize: '20px',
                fontWeight: 800,
                color: C.mint,
                lineHeight: 1.4,
                margin: '12px 0 10px',
                letterSpacing: '-.02em',
              }}
            >
              계단으로 2층 이상 올라가세요.
            </div>
            <div
              style={{
                fontSize: '16px',
                lineHeight: 1.62,
                color: 'rgba(255,255,255,.78)',
              }}
            >
              물이 차면 문이 안 열려요. 물건은 두고 몸만 나오시면 돼요.
            </div>
          </div>

          {/* 근거 인용은 장식이 아니라 제약이다. 근거가 없으면 안내를 하지
              않는다는 원칙을 랜딩에서도 그대로 보여준다. */}
          <div
            style={{
              background: 'rgba(95,201,174,.14)',
              border: '1px solid rgba(95,201,174,.3)',
              borderRadius: '12px',
              padding: '13px 15px',
              marginBottom: '12px',
            }}
          >
            <div
              style={{
                fontSize: '12.5px',
                fontWeight: 700,
                color: C.mintPale,
                marginBottom: '5px',
              }}
            >
              근거 · 국민행동요령 침수편 3-2
            </div>
            <div
              style={{
                fontSize: '14px',
                lineHeight: 1.6,
                color: 'rgba(255,255,255,.8)',
              }}
            >
              “반지하·지하 공간은 침수 시 수압으로 출입문 개방이 불가하므로 즉시
              지상으로 이동한다.”
            </div>
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '9px',
              background: C.teal,
              borderRadius: '12px',
              padding: '14px',
              fontSize: '16px',
              fontWeight: 700,
            }}
          >
            <svg viewBox="0 0 24 24" style={{ ...ICON_BASE, width: 19, height: 19 }}>
              <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
              <path d="M15.5 8.5a5 5 0 0 1 0 7" />
            </svg>
            읽어 드릴까요?
          </div>
        </div>

        <div
          data-reveal
          style={{
            fontSize: '17px',
            lineHeight: 1.66,
            color: C.navy,
            fontWeight: 600,
            marginTop: '20px',
            textAlign: 'center',
            textWrap: 'pretty',
          }}
        >
          ‘유의 바랍니다’가
          <br />
          ‘지금 위층으로’가 됩니다.
        </div>

        {/* ⚠️ 여기에 /preview 체험 링크를 두지 않는다(2026-08-06 제거).
            처음에는 "우리 가족이 이런 안내를 받는구나"를 미리 보여주려고
            공개 홈에 걸었는데, 링크를 거는 순간 /preview 가 실험 화면이
            아니라 방문자·심사위원이 보는 대표 화면이 된다. 그런데 /preview
            에는 이 제품의 핵심 세 가지(생성된 개인화 문구를 그대로 보여주기,
            근거를 함께 보여주기, 다국어·쉬운 말로 보여주기)가 빠져 있고,
            행동 지시 자리에는 근거 없는 하드코딩 문구가 들어간다 —
            "실제 안내 화면"이라는 표현이 사실과 달라진다(PR #54 리뷰,
            머지 전 필수 1). 고정 토큰 p001 을 공개 페이지에서 링크하는 것도
            실배포(VITE_USE_MOCK=false)에서 실존 등록자 토큰과 겹칠 여지를
            남긴다(같은 PR, PM 리뷰).
            검토용 진입 경로는 /demo 안에 이미 있다(App.tsx 의 DemoView —
            "실험적 화면" 섹션). 공개 홈에 다시 걸려면 먼저 message.body 와
            sources 를 이 플로우 안에서 렌더해야 한다. */}
      </section>

      {/* ===================== 03 작동 방식 ===================== */}
      <section style={{ padding: '44px 24px' }}>
        <SectionLabel>03 &nbsp;어떻게 작동하나요</SectionLabel>
        <h2
          data-reveal
          style={{
            fontSize: '27px',
            fontWeight: 800,
            color: C.navy,
            lineHeight: 1.38,
            letterSpacing: '-.025em',
            margin: '0 0 26px',
          }}
        >
          세 단계로
          <br />
          끝납니다
        </h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <StepCard n="1" title="한 번만 등록">
            보호자나 복지관이 <b style={{ color: C.navy }}>대신</b> 등록해
            드립니다. 어르신 본인은 아무것도 하지 않아도 됩니다.
          </StepCard>
          <StepCard n="2" title="위험할 때만 연락">
            특보가 발효되고 등록한 동네가 위험해질 때,{' '}
            <b style={{ color: C.navy }}>알림 한 번</b>으로 알려드립니다. 평소에는
            조용합니다.
          </StepCard>
          <StepCard n="3" title="링크를 누르면 끝" accent>
            설치 없이 바로 열립니다. 지금 계신 자리에서{' '}
            <b style={{ color: C.navy }}>할 행동 하나</b>를 알려드리고, 궁금한
            건 대화로 답해 드립니다.
          </StepCard>
        </div>
      </section>

      {/* ===================== 04 안심 ===================== */}
      <section style={{ background: C.navy, padding: '44px 24px', color: C.white }}>
        <div
          data-reveal
          style={{
            fontFamily: FONT_MONO,
            fontSize: '12px',
            fontWeight: 600,
            letterSpacing: '.16em',
            color: C.mint,
            marginBottom: '12px',
          }}
        >
          04 &nbsp;안심하셔도 됩니다
        </div>
        <h2
          data-reveal
          style={{
            fontSize: '27px',
            fontWeight: 800,
            lineHeight: 1.38,
            letterSpacing: '-.025em',
            margin: '0 0 26px',
          }}
        >
          네 가지는
          <br />
          약속드립니다
        </h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <PromiseCard
            title="근거 없으면 말하지 않습니다"
            body="모든 안내는 행정안전부 국민행동요령 원문에 근거합니다. 근거를 찾지 못하면 아예 답하지 않습니다."
            icon={
              <svg viewBox="0 0 24 24" style={{ ...ICON_BASE, width: 20, height: 20 }}>
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
                <path d="m9 11 2 2 4-4" />
              </svg>
            }
          />
          <PromiseCard
            title="위치는 딱 한 번만"
            body="평소에는 위치를 보지 않습니다. 알림을 열 때 1회만 확인하고, 저장하지 않습니다."
            icon={
              <svg viewBox="0 0 24 24" style={{ ...ICON_BASE, width: 20, height: 20 }}>
                <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
                <circle cx="12" cy="10" r="3" />
              </svg>
            }
          />
          <PromiseCard
            title="설치할 것이 없습니다"
            body="앱스토어에 갈 필요도, 가입할 필요도 없습니다. 링크를 누르면 바로 열립니다."
            icon={
              <svg viewBox="0 0 24 24" style={{ ...ICON_BASE, width: 20, height: 20 }}>
                <path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.5 1.5" />
                <path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7L12 19" />
              </svg>
            }
          />
          <PromiseCard
            title="읽기 어려우면 들으세요"
            body="음성 안내, 쉬운 글, 모국어 번역을 함께 드립니다. 화면낭독기도 그대로 쓰실 수 있습니다."
            icon={
              <svg viewBox="0 0 24 24" style={{ ...ICON_BASE, width: 20, height: 20 }}>
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                <path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14" />
              </svg>
            }
          />
        </div>
      </section>

      {/* ===================== 05 등록 ===================== */}
      <section id="register" style={{ padding: '44px 24px 40px' }}>
        <img
          data-reveal
          src={registerHint}
          alt="스마트폰으로 부모님을 대신 등록하는 딸"
          style={{
            width: '100%',
            display: 'block',
            borderRadius: '22px',
            marginBottom: '26px',
          }}
        />
        <h2
          data-reveal
          style={{
            fontSize: '28px',
            fontWeight: 800,
            color: C.navy,
            lineHeight: 1.38,
            letterSpacing: '-.025em',
            margin: '0 0 16px',
            textWrap: 'pretty',
          }}
        >
          오늘 2분이면
          <br />
          부모님을 등록할 수<br />
          있습니다
        </h2>
        <p
          data-reveal
          style={{
            fontSize: '18px',
            lineHeight: 1.7,
            color: C.body,
            margin: '0 0 24px',
            textWrap: 'pretty',
          }}
        >
          이름, 연락처, 사시는 동네만 있으면 됩니다. 비용은 들지 않습니다. 등록
          후에는 위험할 때만 연락이 갑니다.
        </p>

        <div data-reveal style={{ display: 'flex', gap: '10px', marginBottom: '22px' }}>
          <Stat value="2분" label="등록 소요" />
          <Stat value="무료" label="이용 비용" />
          <Stat value="0개" label="설치할 앱" />
        </div>

        <a
          href={REGISTER_URL}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '9px',
            background: C.teal,
            color: C.white,
            borderRadius: '16px',
            padding: '20px',
            fontSize: '18px',
            fontWeight: 800,
            letterSpacing: '-.01em',
            marginBottom: '12px',
            textDecoration: 'none',
            minHeight: '56px',
          }}
        >
          내 가족 등록해주기
          <svg viewBox="0 0 24 24" style={{ ...ICON_BASE, width: 19, height: 19 }}>
            <path d="m9 18 6-6-6-6" />
          </svg>
        </a>
        <a
          href="/ops"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: C.white,
            color: C.tealText,
            border: `1.5px solid ${C.tealText}`,
            borderRadius: '16px',
            padding: '19px',
            fontSize: '17px',
            fontWeight: 700,
            textDecoration: 'none',
            minHeight: '56px',
          }}
        >
          복지관·지자체 담당자세요?
        </a>
        <div
          style={{
            fontSize: '14px',
            lineHeight: 1.7,
            color: C.tertiary,
            marginTop: '16px',
            textAlign: 'center',
          }}
        >
          복지관·지자체를 통한 대리등록도 가능합니다.
        </div>
      </section>

      {/* ===================== FOOTER ===================== */}
      <footer
        style={{
          background: C.navy,
          padding: '32px 24px 40px',
          color: 'rgba(255,255,255,.6)',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            marginBottom: '16px',
          }}
        >
          <img
            src={logoLight}
            alt=""
            style={{
              width: '22px',
              height: '22px',
              display: 'block',
              objectFit: 'contain',
            }}
          />
          <span style={{ fontSize: '16px', fontWeight: 800, color: C.white }}>
            SAVERS
          </span>
        </div>
        <div style={{ fontSize: '14px', lineHeight: 1.8 }}>
          팀 세이버스 · 2026 제8회 K-디지털 트레이닝 해커톤
          <br />
          데이터 출처: 행정안전부 국민행동요령, 기상청 특보 API
          <br />
          세이버스는 긴급재난문자를 대체하지 않고 보완합니다.
        </div>
        <div
          style={{
            fontFamily: FONT_MONO,
            fontSize: '11px',
            letterSpacing: '.06em',
            color: 'rgba(255,255,255,.35)',
            marginTop: '20px',
          }}
        >
          © 2026 TEAM SAVERS
        </div>
      </footer>

      {/* 하단 상시 CTA. 히어로 CTA가 화면에서 나간 뒤에만 나타난다. */}
      {showStickyCta && (
        <div
          style={{
            position: 'fixed',
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 30,
            display: 'flex',
            justifyContent: 'center',
            pointerEvents: 'none',
          }}
        >
          <div
            style={{
              width: '100%',
              maxWidth: '402px',
              padding: '12px 16px 16px',
              background:
                'linear-gradient(180deg,rgba(244,248,247,0),rgba(244,248,247,.96) 42%)',
              pointerEvents: 'auto',
            }}
          >
            <a
              href={REGISTER_URL}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px',
                background: C.navy,
                color: C.white,
                borderRadius: '15px',
                padding: '17px',
                fontSize: '17px',
                fontWeight: 800,
                textDecoration: 'none',
                minHeight: '56px',
                boxShadow: '0 10px 28px -12px rgba(13,43,69,.6)',
              }}
            >
              2분이면 됩니다 · 내 가족 등록해주기
            </a>
          </div>
        </div>
      )}
    </main>
  )
}
