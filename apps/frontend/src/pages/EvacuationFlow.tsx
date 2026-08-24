import { useEffect, useState, type ReactNode } from 'react'
import { mockAlert, mockProfile, mockRoute, mockShelter } from '../mocks/evacuation'
import { speechScripts } from '../mocks/evacuationSpeech'
import './EvacuationFlow.css'

export type EvacuationStep = 'alert' | 'profile' | 'choice' | 'help' | 'shelter' | 'route' | 'arrival'
type Step = EvacuationStep
type Action = 'help' | 'self' | null

export function EvacuationFlow() {
  const [currentStep, setCurrentStep] = useState<Step>('alert')
  const [preregistered] = useState(mockProfile.preregistered)
  const [selectedAction, setSelectedAction] = useState<Action>(null)
  const [arrivalConfirmed, setArrivalConfirmed] = useState(false)
  const [largeText, setLargeText] = useState(false)
  const [speechEnabled, setSpeechEnabled] = useState(false)

  useEffect(() => {
    if (!speechEnabled || typeof window === 'undefined' || !('speechSynthesis' in window)) return
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(speechScripts[currentStep])
    utterance.lang = 'ko-KR'
    window.speechSynthesis.speak(utterance)
    return () => window.speechSynthesis.cancel()
  }, [currentStep, speechEnabled])

  useEffect(() => () => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel()
    }
  }, [])

  const goHome = () => {
    setCurrentStep('alert')
    setSelectedAction(null)
    setArrivalConfirmed(false)
  }

  const choose = (action: Exclude<Action, null>) => {
    setSelectedAction(action)
    setCurrentStep(action === 'help' ? 'help' : 'shelter')
  }

  const toggleSpeech = () => {
    if (speechEnabled && typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel()
    }
    setSpeechEnabled((enabled) => !enabled)
  }

  return (
    <MobileFlowLayout
      canGoBack={currentStep !== 'alert'}
      largeText={largeText}
      onBack={() => setCurrentStep(previousStep(currentStep, preregistered))}
    >
      {currentStep === 'alert' && (
        <DisasterAlertStep
          onNext={() => setCurrentStep(preregistered ? 'choice' : 'profile')}
          largeText={largeText}
          speechEnabled={speechEnabled}
          onToggleLargeText={() => setLargeText((enabled) => !enabled)}
          onToggleSpeech={toggleSpeech}
        />
      )}
      {currentStep === 'profile' && <ProfileInputStep onNext={() => setCurrentStep('choice')} />}
      {currentStep === 'choice' && <ActionChoiceStep selected={selectedAction} onChoose={choose} />}
      {currentStep === 'help' && <HelpRequestStep onHome={goHome} />}
      {currentStep === 'shelter' && <ShelterRecommendationStep onNext={() => setCurrentStep('route')} />}
      {currentStep === 'route' && <RouteGuidanceStep onArrival={() => { setArrivalConfirmed(true); setCurrentStep('arrival') }} />}
      {currentStep === 'arrival' && <ArrivalCompleteStep confirmed={arrivalConfirmed} onHome={goHome} />}
    </MobileFlowLayout>
  )
}

function previousStep(step: Step, preregistered: boolean): Step {
  const previous: Record<Step, Step> = {
    alert: 'alert', profile: 'alert', choice: preregistered ? 'alert' : 'profile', help: 'choice',
    shelter: 'choice', route: 'shelter', arrival: 'route',
  }
  return previous[step]
}

function MobileFlowLayout({
  children,
  canGoBack,
  largeText,
  onBack,
}: {
  children: ReactNode
  canGoBack: boolean
  largeText: boolean
  onBack: () => void
}) {
  return (
    <main className={`evac-flow${largeText ? ' is-large-text' : ''}`}>
      <header className="evac-header">
        <button className={`evac-back${canGoBack ? '' : ' is-hidden'}`} type="button" onClick={onBack} aria-label="이전 화면">← 뒤로</button>
        <strong className="evac-brand"><img src="/logo.png" alt="" />SAVERS</strong>
        <span aria-hidden="true" />
      </header>
      <div className="evac-content">{children}</div>
    </main>
  )
}

// Accessibility settings row — shown only inside the alert step's footer,
// below the CTA. Two real <button role="switch"> elements (not a styled
// checkbox/label pair) so aria-checked + keyboard activation come for
// free. State/handlers are passed through unchanged from EvacuationFlow;
// this component owns no state of its own.
function AccessibilityRow({
  largeText,
  speechEnabled,
  onToggleLargeText,
  onToggleSpeech,
}: {
  largeText: boolean
  speechEnabled: boolean
  onToggleLargeText: () => void
  onToggleSpeech: () => void
}) {
  return (
    <div className="evac-accessibility-row" aria-label="접근성 설정">
      <button
        type="button"
        role="switch"
        aria-checked={largeText}
        className="evac-a11y-toggle evac-a11y-large-text"
        onClick={onToggleLargeText}
      >
        <span className="evac-a11y-label">글자 크게</span>
        <span className="evac-switch" aria-hidden="true"><span className="evac-switch-thumb" /></span>
      </button>
      <button
        type="button"
        role="switch"
        aria-checked={speechEnabled}
        className="evac-a11y-toggle evac-a11y-speech"
        onClick={onToggleSpeech}
      >
        <span className="evac-a11y-label">음성 안내</span>
        <span className="evac-switch" aria-hidden="true"><span className="evac-switch-thumb" /></span>
      </button>
    </div>
  )
}

function PrimaryButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return <button className="evac-primary" type="button" onClick={onClick}>{children}</button>
}

function OfficialNotice() {
  return <p className="evac-footnote">상황은 변할 수 있습니다.<br />재난문자와 공식 채널을 함께 확인하세요.</p>
}

function StepFooter({ children }: { children?: ReactNode }) {
  return <footer className="evac-footer">{children}<OfficialNotice /></footer>
}

function DisasterAlertStep({
  onNext,
  largeText,
  speechEnabled,
  onToggleLargeText,
  onToggleSpeech,
}: {
  onNext: () => void
  largeText: boolean
  speechEnabled: boolean
  onToggleLargeText: () => void
  onToggleSpeech: () => void
}) {
  return <section className="evac-step evac-step-centered evac-alert-step">
    <div className="evac-content-group"><div className="evac-alert-main">
      <div className="evac-alert-icon-wrap" aria-hidden="true">
        <div className="evac-alert-icon">!</div>
      </div>
      <p className="evac-kicker">긴급 재난 정보</p>
      <h1>{mockAlert.area}에 <em>{mockAlert.warning}</em>가<br />발령되었습니다.</h1>
    </div>
      <div className="evac-card evac-notice"><span aria-hidden="true">🔔</span><div><strong>{mockAlert.source}</strong><small>{mockAlert.announcedAt}</small></div></div>
      <StepFooter>
        <PrimaryButton onClick={onNext}>상황 확인하기</PrimaryButton>
        <AccessibilityRow
          largeText={largeText}
          speechEnabled={speechEnabled}
          onToggleLargeText={onToggleLargeText}
          onToggleSpeech={onToggleSpeech}
        />
      </StepFooter></div>
  </section>
}

function ProfileInputStep({ onNext }: { onNext: () => void }) {
  const [age, setAge] = useState('')
  const [gender, setGender] = useState('')
  const hasAnyInput = age.trim() !== '' || gender !== ''

  return (
    <section className="evac-step evac-step-distributed">
      <div className="evac-content-group">
        <div className="evac-intro">
          <h1>
            맞춤 안내를 위해
            <br />
            <em className="blue">정보를 확인할게요</em>
          </h1>
          <p className="evac-lead">
            재난 대응에 필요한 최소 정보만 확인합니다.
          </p>
        </div>

        <div className="evac-card evac-profile evac-profile-input">
          <label>
            나이
            <input
              aria-label="나이"
              inputMode="numeric"
              min="0"
              max="120"
              placeholder="예: 72"
              type="number"
              value={age}
              onChange={(event) => setAge(event.target.value)}
            />
          </label>
          <label>
            성별
            <select aria-label="성별" value={gender} onChange={(event) => setGender(event.target.value)}>
              <option value="">선택하지 않음</option>
              <option value="female">여성</option>
              <option value="male">남성</option>
              <option value="other">기타</option>
            </select>
          </label>
        </div>

        <StepFooter>
          <button className="evac-primary" type="button" disabled={!hasAnyInput} onClick={onNext}>다음</button>
          <button className="evac-profile-skip" type="button" onClick={onNext}>건너뛰기</button>
        </StepFooter>
      </div>
    </section>
  )
}

function ActionChoiceStep({
  selected,
  onChoose,
}: {
  selected: Action
  onChoose: (action: Exclude<Action, null>) => void
}) {
  return (
    <section className="evac-step evac-step-choice">
      <div className="evac-content-group">
        <div className="evac-intro">
          <h1>어떻게 도와드릴까요?</h1>
          <p className="evac-lead">필요한 도움을 선택해주세요.</p>
        </div>

        <div className="evac-choice-list">
          <button
            className={`evac-card evac-choice${selected === 'help' ? ' selected' : ''
              }`}
            type="button"
            onClick={() => onChoose('help')}
          >
            <span className="evac-choice-icon accent" aria-hidden="true">
              🛟
            </span>
            <span>
              <strong>도움이 필요해요</strong>
              <small>선택한 사실을 표시하고 119 연결을 안내합니다</small>
            </span>
            <b aria-hidden="true">›</b>
          </button>

          <button
            className={`evac-card evac-choice${selected === 'self' ? ' selected' : ''
              }`}
            type="button"
            onClick={() => onChoose('self')}
          >
            <span className="evac-choice-icon" aria-hidden="true">
              🚶
            </span>
            <span>
              <strong>혼자서 대피할게요</strong>
              <small>안전 필터를 거친 대피 경로를 안내합니다</small>
            </span>
            <b aria-hidden="true">›</b>
          </button>
        </div>
      </div>

      <OfficialNotice />
    </section>
  )
}

function HelpRequestStep({ onHome }: { onHome: () => void }) {
  return <section className="evac-step evac-step-centered evac-success"><div className="evac-content-group"><div className="evac-step-main"><div className="evac-check">✓</div><h1>도움이 필요하다고<br /><em>표시했습니다.</em></h1><p>긴급한 상황이라면 119에 바로 연락해주세요.</p></div><StepFooter><a className="evac-primary" href="tel:119">☎ 119 전화하기</a><button className="evac-secondary" type="button" onClick={onHome}>처음으로</button></StepFooter></div></section>
}

function EvacuationLevels() { return <div className="evac-levels" aria-label="대피 단계"><div><i />상황 주시<small>정보 확인</small></div><div><i />대피 준비<small>용품 준비</small></div><div className="active"><i />즉시 대피<small>현재 단계</small></div></div> }

function ShelterRecommendationStep({
  onNext,
}: {
  onNext: () => void
}) {
  return (
    <section className="evac-step evac-step-distributed">
      <div className="evac-content-group">
        <div className="evac-shelter-intro">
          <EvacuationLevels />
          <h1>
            지금은 <em>「즉시 대피」</em>
            <br />
            여기로 가세요
          </h1>
        </div>

        <div className="evac-shelter-body">
          <article className="evac-card evac-shelter">
            <h2>{mockShelter.name}</h2>
            <p>
              {mockShelter.address} · {mockShelter.type}
            </p>

            <div className="evac-tags">
              {mockShelter.tags.map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
            </div>

            <strong className="evac-distance">
              <b>{mockShelter.minutes}</b>분 · 침수 회피 경로{' '}
              {mockShelter.distance}
            </strong>

            <div className="evac-deadline">
              <span>
                출입 권고 마감
                <b>{mockShelter.recommendationDeadline}</b>
              </span>
              <span>
                남은 시간
                <b>{mockShelter.minutesRemaining}분</b>
              </span>
            </div>
          </article>

          <p className="evac-route-note">
            지하 주차장 2곳 제외 · {mockAlert.source}
          </p>
        </div>

        <StepFooter>
          <PrimaryButton onClick={onNext}>경로 보기</PrimaryButton>
        </StepFooter>
      </div>
    </section>
  )
}

function RouteGuidanceStep({
  onArrival,
}: {
  onArrival: () => void
}) {
  return (
    <section className="evac-step evac-step-distributed evac-route-step">
      <div className="evac-content-group">
        <div className="evac-route-intro">
          <h1>이 길로 가세요</h1>
          <p className="evac-lead">
            가장 짧은 길은 차단 구간 {mockRoute.blockedSegments}곳을
            지나므로 사용하지 않습니다.
          </p>
        </div>

        <div className="evac-route-body">
          <div
            className="evac-map"
            role="img"
            aria-label="현재 위치에서 대피소까지 침수 구역을 피하는 예시 경로"
          >
            <div className="flood-zone">침수예상구역</div>
            <div className="safe-line line-a" />
            <div className="safe-line line-b" />
            <div className="safe-line line-c" />
            <div className="short-line" />

            <span className="map-label start">현재 위치</span>
            <span className="map-label end">추천 대피소</span>

            <span className="blocked b1">×</span>
            <span className="blocked b2">×</span>
            <span className="blocked b3">×</span>
          </div>

          <div className="evac-route-stats">
            <div className="active">
              안내 · 침수 회피
              <strong>
                {mockRoute.avoidedDistance} · {mockRoute.avoidedMinutes}분
              </strong>
            </div>

            <div>
              최단 · 미사용
              <strong>{mockRoute.unusedShortestDistance}</strong>
            </div>
          </div>

          <div className="evac-legend">
            <span>
              <i className="safe" />
              회피 경로
            </span>
            <span>
              <i className="short" />
              미사용 최단 경로
            </span>
            <span>
              <i className="water" />
              침수예상구역
            </span>
            <span>
              <i className="block" />
              차단 구간
            </span>
          </div>

          <p className="evac-user-note">
            도착 완료는 GPS 확인이 아니라 사용자가 직접 표시하는 버튼입니다.
          </p>
        </div>

        <StepFooter>
          <PrimaryButton onClick={onArrival}>도착 완료</PrimaryButton>
        </StepFooter>
      </div>
    </section>
  )
}

function ArrivalCompleteStep({ confirmed, onHome }: { confirmed: boolean; onHome: () => void }) {
  return <section className="evac-step evac-step-centered evac-success"><div className="evac-content-group"><div className="evac-step-main"><div className="evac-check">✓</div><h1>{confirmed ? '도착 완료로' : '도착 상태를'}<br /><em>표시했습니다.</em></h1><p>필요한 경우 재난문자와 공식 안내를 계속 확인해주세요.</p><div className="evac-card evac-user-confirmed"><strong>사용자가 직접 누른 기록</strong><span>GPS로 도착을 판정하지 않았습니다.</span></div></div><StepFooter><button className="evac-secondary" type="button" onClick={onHome}>처음으로</button></StepFooter></div></section>
}
