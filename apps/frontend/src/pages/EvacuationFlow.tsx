import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Guardian, Language, SessionResponse, Shelter, ShelterCaution, ShelterExclusion, ShelterList } from '../api/types'
import { useEvacuationActionFlow } from '../hooks/useEvacuationActionFlow'
import { useShelterSearch } from '../hooks/useShelterSearch'
import { applyDocumentLanguage, countUnit, excludedReasonLabel, t } from '../lib/i18n'
import './EvacuationFlow.css'

// v0.9 (ADR-0016): 계약이 정의한 문구가 아니라 화면이 붙이는 라벨이다
// (openapi.yaml Shelter.cautions는 문구를 고정하지 않고 값만 stairs/
// over_time으로 좁힌다). "제외"가 아니라 "주의"라는 톤을 유지 —
// 위험/사용불가 같은 과도한 표현을 쓰지 않는다.
const CAUTION_LABEL: Record<ShelterCaution, string> = {
  stairs: '계단 이용 주의',
  over_time: '이동 시간 주의',
}

export type EvacuationStep = 'alert' | 'profile' | 'choice' | 'help' | 'shelter' | 'route' | 'arrival'
type Step = EvacuationStep
type Action = 'help' | 'self' | null

export interface EvacuationDemoData {
  alert: { area: string; warning: string; source: string; announcedAt: string }
  guardian: Guardian | null
  preregistered: boolean
  shelter: {
    name: string; address: string; type: string; minutes: number; distance: string
    tags: readonly string[]; cautions: ShelterCaution[]; recommendationDeadline: string; minutesRemaining: number
  }
  route: { blockedSegments: number; avoidedDistance: string; avoidedMinutes: number; unusedShortestDistance: string }
  speech: Record<EvacuationStep, string>
}

export function EvacuationFlow({ demo }: { demo: EvacuationDemoData }) {
  const [currentStep, setCurrentStep] = useState<Step>('alert')
  const [preregistered] = useState(demo.preregistered)
  const [selectedAction, setSelectedAction] = useState<Action>(null)
  const [largeText, setLargeText] = useState(false)
  const [speechEnabled, setSpeechEnabled] = useState(false)
  // Lifted out of ProfileInputStep so profile → choice → back → profile
  // keeps what the user typed. ProfileInputStep is conditionally rendered
  // (only mounted while currentStep === 'profile'), so local state there
  // is lost on every remount; this is the flow-level single source of
  // truth instead.
  const [age, setAge] = useState('')
  const [gender, setGender] = useState('')

  useEffect(() => {
    if (!speechEnabled || typeof window === 'undefined' || !('speechSynthesis' in window)) return
    window.speechSynthesis.cancel()
    // Android Chrome can silently drop a speak() issued in the same tick
    // as the preceding cancel() — deferring one task lets cancel() finish
    // first. The cleanup below clears this timer, so a step/speechEnabled
    // change before it fires (or an unmount) never lets the stale
    // utterance play late.
    const timerId = window.setTimeout(() => {
      const utterance = new SpeechSynthesisUtterance(demo.speech[currentStep])
      utterance.lang = 'ko-KR'
      window.speechSynthesis.speak(utterance)
    }, 0)
    return () => {
      window.clearTimeout(timerId)
      window.speechSynthesis.cancel()
    }
  }, [currentStep, demo.speech, speechEnabled])

  useEffect(() => () => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel()
    }
  }, [])

  const goHome = () => {
    setCurrentStep('alert')
    setSelectedAction(null)
    // Restarting the flow from scratch is the one action meant to clear
    // profile input — back navigation alone must not (blocking #4). This
    // also preserves the pre-lift behavior, where remounting
    // ProfileInputStep on every 'alert' visit reset age/gender anyway.
    setAge('')
    setGender('')
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
      speechEnabled={speechEnabled}
      onToggleSpeech={toggleSpeech}
      // The alert step already exposes the speech toggle via
      // AccessibilityRow in its footer — showing this one too would be a
      // duplicate control on the same screen. Every step after it has no
      // other way to turn speech off, which is exactly blocking #3.
      showSpeechToggle={currentStep !== 'alert'}
    >
      {currentStep === 'alert' && (
        <DisasterAlertStep
          onNext={() => setCurrentStep(preregistered ? 'choice' : 'profile')}
          largeText={largeText}
          speechEnabled={speechEnabled}
          onToggleLargeText={() => setLargeText((enabled) => !enabled)}
          onToggleSpeech={toggleSpeech}
          demoAlert={demo.alert}
        />
      )}
      {currentStep === 'profile' && (
        <ProfileInputStep
          age={age}
          gender={gender}
          onAgeChange={setAge}
          onGenderChange={setGender}
          onNext={() => setCurrentStep('choice')}
        />
      )}
      {currentStep === 'choice' && <ActionChoiceStep selected={selectedAction} onChoose={choose} />}
      {currentStep === 'help' && <HelpRequestStep guardian={demo.guardian} onHome={goHome} />}
      {currentStep === 'shelter' && <ShelterRecommendationStep onNext={() => setCurrentStep('route')} demoShelter={demo.shelter} demoAlert={demo.alert} />}
      {currentStep === 'route' && <RouteGuidanceStep onArrival={() => setCurrentStep('arrival')} demoRoute={demo.route} />}
      {currentStep === 'arrival' && <ArrivalCompleteStep onHome={goHome} />}
    </MobileFlowLayout>
  )
}

interface ProductionProps {
  token: string
  session: SessionResponse
  suppressBody: boolean
}

const FLOW_COPY = {
  ko: {
    emergency: '긴급 재난 정보', check: '상황 확인하기', choiceTitle: '어떻게 도와드릴까요?',
    choiceBody: '필요한 도움을 선택해주세요.', help: '도움이 필요해요',
    helpBody: '보호자 또는 119에 연락할 수 있도록 안내합니다', direct: '혼자서 대피할게요',
    directBody: '안전 필터를 거친 대피 경로를 안내합니다', helpTitle: '어떤 도움이 필요하세요?',
    helpPrompt: '연락할 곳을 선택해주세요.', guardian: '👤 보호자에게 연락하기', call119: '🚨 119에 연락하기',
    backHome: '처음으로', immediate: '지금은 「즉시 대피」', goHere: '여기로 가세요',
    route: '경로 보기', routeTitle: '이 길로 가세요', arrival: '도착했어요',
    arrivalTitle: '도착 완료로 표시했습니다.', arrivalBody: '필요한 경우 재난문자와 공식 안내를 계속 확인해주세요.',
    failure: '행동 기록을 저장하지 못했습니다.', retry: '다시 시도', continuingHelp: '기록 없이 도움 요청 계속하기',
    continuingShelter: '기록 없이 대피소 보기', official: '상황은 변할 수 있습니다. 재난문자와 공식 채널을 함께 확인하세요.',
    suppressed: '근거를 확인할 수 없어 행동 지시문을 표시하지 않습니다.',
  },
  vi: {
    emergency: 'Thông tin thiên tai khẩn cấp', check: 'Kiểm tra tình hình', choiceTitle: 'Bạn cần hỗ trợ như thế nào?',
    choiceBody: 'Hãy chọn sự hỗ trợ bạn cần.', help: 'Tôi cần giúp đỡ',
    helpBody: 'Hướng dẫn gọi người giám hộ hoặc 119', direct: 'Tôi sẽ tự sơ tán',
    directBody: 'Hướng dẫn nơi trú ẩn đã qua bộ lọc an toàn', helpTitle: 'Bạn cần hỗ trợ gì?',
    helpPrompt: 'Hãy chọn nơi cần gọi.', guardian: '👤 Gọi người giám hộ', call119: '🚨 Gọi 119',
    backHome: 'Về đầu', immediate: 'Hiện tại: 「Sơ tán ngay」', goHere: 'Hãy đến đây',
    route: 'Xem đường đi', routeTitle: 'Hãy đi theo đường này', arrival: 'Đã đến nơi',
    arrivalTitle: 'Đã ghi nhận bạn đến nơi.', arrivalBody: 'Hãy tiếp tục kiểm tra tin nhắn thiên tai và hướng dẫn chính thức khi cần.',
    failure: 'Không thể lưu hành động.', retry: 'Thử lại', continuingHelp: 'Tiếp tục yêu cầu trợ giúp mà không lưu',
    continuingShelter: 'Xem nơi trú ẩn mà không lưu', official: 'Tình hình có thể thay đổi. Hãy kiểm tra cả tin nhắn thiên tai và kênh chính thức.',
    suppressed: 'Không hiển thị chỉ dẫn hành động vì không xác minh được nguồn căn cứ.',
  },
} as const
type FlowCopy = (typeof FLOW_COPY)[keyof typeof FLOW_COPY]
const FlowCopyContext = createContext<FlowCopy | null>(null)
const STAGE_COPY = {
  ko: {
    1: { label: '상황 주시', title: '지금은 「상황 주시」', action: '공식 안내를 확인하세요' },
    2: { label: '대피 준비', title: '지금은 「대피 준비」', action: '대피할 준비를 하세요' },
    3: { label: '즉시 대피', title: '지금은 「즉시 대피」', action: '여기로 가세요' },
  },
  vi: {
    1: { label: 'Theo dõi tình hình', title: 'Hiện tại: 「Theo dõi tình hình」', action: 'Hãy kiểm tra hướng dẫn chính thức' },
    2: { label: 'Chuẩn bị sơ tán', title: 'Hiện tại: 「Chuẩn bị sơ tán」', action: 'Hãy chuẩn bị sơ tán' },
    3: { label: 'Sơ tán ngay', title: 'Hiện tại: 「Sơ tán ngay」', action: 'Hãy đến đây' },
  },
} as const

export function ProductionEvacuationFlow({ token, session, suppressBody }: ProductionProps) {
  const lang: 'ko' | 'vi' = session.profile.language === 'vi' ? 'vi' : 'ko'
  const copy = FLOW_COPY[lang]
  const [currentStep, setCurrentStep] = useState<Step>('alert')
  const [selectedAction, setSelectedAction] = useState<Action>(null)
  const [largeText, setLargeText] = useState(false)
  const [speechEnabled, setSpeechEnabled] = useState(false)
  const actions = useEvacuationActionFlow(token)
  const shelterState = useShelterSearch(token, session.profile)
  const stageCopy = STAGE_COPY[lang][session.stage]
  const stairsState = session.profile.fromRegistration === true
    ? 'unknown'
    : session.profile.stairsOk
      ? 'ok'
      : 'blocked'
  const nextActionKey = stairsState === 'ok'
    ? 'shelter.nextAction.stairsOk'
    : stairsState === 'blocked'
      ? 'shelter.nextAction.stairsBlocked'
      : 'shelter.nextAction.stairsUnknown'
  const speechText = useMemo(() => {
    if (currentStep === 'alert') return `${session.message.title}. ${suppressBody ? copy.suppressed : session.message.body}`
    if (currentStep === 'choice') return `${copy.choiceTitle} ${copy.choiceBody}`
    if (currentStep === 'help') return `${copy.helpTitle} ${copy.helpPrompt}`
    if (currentStep === 'shelter') return `${stageCopy.title}. ${stageCopy.action}`
    if (currentStep === 'route') return `${stageCopy.label}. ${copy.routeTitle}`
    return `${copy.arrivalTitle} ${copy.arrivalBody}`
  }, [copy, currentStep, session.message, stageCopy, suppressBody])

  useEffect(() => applyDocumentLanguage(lang), [lang])
  useEffect(() => {
    if (!speechEnabled || !('speechSynthesis' in window)) return
    window.speechSynthesis.cancel()
    const timer = window.setTimeout(() => {
      const utterance = new SpeechSynthesisUtterance(speechText)
      utterance.lang = lang === 'vi' ? 'vi-VN' : 'ko-KR'
      window.speechSynthesis.speak(utterance)
    }, 0)
    return () => { window.clearTimeout(timer); window.speechSynthesis.cancel() }
  }, [lang, speechEnabled, speechText])

  const back = () => {
    if (actions.pendingRef.current) return
    actions.clearFailure()
    setCurrentStep(previousStep(currentStep, true))
  }
  const choose = (action: Exclude<Action, null>) => {
    setSelectedAction(action)
    if (action === 'help') {
      actions.run(['help_request_selected'], () => { setCurrentStep('help') }, () => {
        actions.clearFailure(); setCurrentStep('help')
      })
      return
    }
    actions.run(['direct_evacuation_selected', 'evacuation_guidance_viewed'], () => {
      setCurrentStep('shelter')
    }, () => { actions.clearFailure(); setCurrentStep('shelter') })
  }
  const toggleSpeech = () => {
    if (speechEnabled && 'speechSynthesis' in window) window.speechSynthesis.cancel()
    setSpeechEnabled((value) => !value)
  }
  const goHome = () => { if (!actions.pendingRef.current) { actions.clearFailure(); setSelectedAction(null); setCurrentStep('alert') } }

  return <FlowCopyContext.Provider value={copy}><MobileFlowLayout
    canGoBack={currentStep !== 'alert'} largeText={largeText} onBack={back}
    speechEnabled={speechEnabled} onToggleSpeech={toggleSpeech} showSpeechToggle={currentStep !== 'alert'}
  >
    {currentStep === 'alert' && <DisasterAlertStep
      onNext={() => setCurrentStep('choice')} largeText={largeText} speechEnabled={speechEnabled}
      onToggleLargeText={() => setLargeText((value) => !value)} onToggleSpeech={toggleSpeech}
      title={session.message.title} body={suppressBody ? copy.suppressed : session.message.body}
      copy={{ emergency: copy.emergency, check: copy.check }}
    />}
    {currentStep === 'choice' && <ActionChoiceStep
      selected={selectedAction} onChoose={choose} copy={copy} pending={actions.pending}
      failure={actions.error === null ? null : <ActionFailureView
        copy={copy} retry={actions.failure?.retry} continueWithoutRecord={actions.failure?.continueWithoutRecord}
        continueLabel={selectedAction === 'help' ? copy.continuingHelp : copy.continuingShelter}
      />}
    />}
    {currentStep === 'help' && <HelpRequestStep guardian={session.profile.guardian} onHome={goHome}
      copy={copy} onCall119={() => actions.recordBestEffort('emergency_call_119_selected')} />}
    {currentStep === 'shelter' && <ShelterRecommendationStep
      onNext={() => actions.run(['route_guidance_started'], () => setCurrentStep('route'))}
      stage={session.stage} stageLabel={stageCopy.label} stageAction={stageCopy.action}
      shelterState={shelterState} pending={actions.pending}
      nextAction={t(nextActionKey, lang)}
      failure={actions.error === null ? null : <ActionFailureView copy={copy} retry={actions.failure?.retry} />}
    />}
    {currentStep === 'route' && <RouteGuidanceStep
      onArrival={() => actions.run(['arrival_confirmed_by_user'], () => setCurrentStep('arrival'))}
      production shelter={shelterState.result?.items[0] ?? null} pending={actions.pending}
      failure={actions.error === null ? null : <ActionFailureView copy={copy} retry={actions.failure?.retry} />}
      copy={copy} stageLabel={stageCopy.label}
    />}
    {currentStep === 'arrival' && <ArrivalCompleteStep onHome={goHome} copy={copy} />}
  </MobileFlowLayout></FlowCopyContext.Provider>
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
  speechEnabled,
  onToggleSpeech,
  showSpeechToggle,
}: {
  children: ReactNode
  canGoBack: boolean
  largeText: boolean
  onBack: () => void
  speechEnabled: boolean
  onToggleSpeech: () => void
  showSpeechToggle: boolean
}) {
  const copy = useContext(FlowCopyContext)
  const isVietnamese = copy === FLOW_COPY.vi
  return (
    <main className={`evac-flow${largeText ? ' is-large-text' : ''}`}>
      <header className="evac-header">
        <button className={`evac-back${canGoBack ? '' : ' is-hidden'}`} type="button" onClick={onBack} aria-label={isVietnamese ? 'Màn hình trước' : '이전 화면'}>{isVietnamese ? '← Quay lại' : '← 뒤로'}</button>
        <strong className="evac-brand"><img src="/logo.png" alt="" />SAVERS</strong>
        {showSpeechToggle ? (
          <button
            type="button"
            role="switch"
            aria-checked={speechEnabled}
            className="evac-header-speech-toggle"
            onClick={onToggleSpeech}
            aria-label={isVietnamese ? (speechEnabled ? 'Tắt hướng dẫn bằng giọng nói' : 'Bật hướng dẫn bằng giọng nói') : (speechEnabled ? '음성 안내 끄기' : '음성 안내 켜기')}
          >
            <span aria-hidden="true">{speechEnabled ? '🔊' : '🔈'}</span>
          </button>
        ) : (
          <span aria-hidden="true" />
        )}
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
  const copy = useContext(FlowCopyContext)
  const isVietnamese = copy === FLOW_COPY.vi
  return (
    <div className="evac-accessibility-row" aria-label={isVietnamese ? 'Cài đặt hỗ trợ tiếp cận' : '접근성 설정'}>
      <button
        type="button"
        role="switch"
        aria-checked={largeText}
        className="evac-a11y-toggle evac-a11y-large-text"
        onClick={onToggleLargeText}
      >
        <span className="evac-a11y-label">{isVietnamese ? 'Chữ lớn' : '글자 크게'}</span>
        <span className="evac-switch" aria-hidden="true"><span className="evac-switch-thumb" /></span>
      </button>
      <button
        type="button"
        role="switch"
        aria-checked={speechEnabled}
        className="evac-a11y-toggle evac-a11y-speech"
        onClick={onToggleSpeech}
      >
        <span className="evac-a11y-label">{isVietnamese ? 'Hướng dẫn giọng nói' : '음성 안내'}</span>
        <span className="evac-switch" aria-hidden="true"><span className="evac-switch-thumb" /></span>
      </button>
    </div>
  )
}

function PrimaryButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return <button className="evac-primary" type="button" onClick={onClick}>{children}</button>
}

function OfficialNotice() {
  const copy = useContext(FlowCopyContext)
  if (copy !== null) return <p className="evac-footnote">{copy.official}</p>
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
  title,
  body,
  copy,
  demoAlert,
}: {
  onNext: () => void
  largeText: boolean
  speechEnabled: boolean
  onToggleLargeText: () => void
  onToggleSpeech: () => void
  title?: string
  body?: string
  copy?: Pick<FlowCopy, 'emergency' | 'check'>
  demoAlert?: EvacuationDemoData['alert']
}) {
  return <section className="evac-step evac-step-centered evac-alert-step">
    <div className="evac-content-group"><div className="evac-alert-main">
      <div className="evac-alert-icon-wrap" aria-hidden="true">
        <div className="evac-alert-icon">!</div>
      </div>
      <p className="evac-kicker">{copy?.emergency ?? '긴급 재난 정보'}</p>
      {title === undefined
        ? <h1>{demoAlert?.area}에 <em>{demoAlert?.warning}</em>가<br />발령되었습니다.</h1>
        : <h1>{title}</h1>}
    </div>
      <div className="evac-card evac-notice"><span aria-hidden="true">🔔</span><div>
        {body === undefined
          ? <><strong>{demoAlert?.source}</strong><small>{demoAlert?.announcedAt}</small></>
          : <strong>{body}</strong>}
      </div></div>
      <StepFooter>
        <PrimaryButton onClick={onNext}>{copy?.check ?? '상황 확인하기'}</PrimaryButton>
        <AccessibilityRow
          largeText={largeText}
          speechEnabled={speechEnabled}
          onToggleLargeText={onToggleLargeText}
          onToggleSpeech={onToggleSpeech}
        />
      </StepFooter></div>
  </section>
}

function ProfileInputStep({
  age,
  gender,
  onAgeChange,
  onGenderChange,
  onNext,
}: {
  age: string
  gender: string
  onAgeChange: (value: string) => void
  onGenderChange: (value: string) => void
  onNext: () => void
}) {
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
              onChange={(event) => onAgeChange(event.target.value)}
            />
          </label>
          <label>
            성별
            <select aria-label="성별" value={gender} onChange={(event) => onGenderChange(event.target.value)}>
              <option value="">선택하지 않음</option>
              <option value="female">여성</option>
              <option value="male">남성</option>
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
  copy,
  pending = false,
  failure,
}: {
  selected: Action
  onChoose: (action: Exclude<Action, null>) => void
  copy?: FlowCopy
  pending?: boolean
  failure?: ReactNode
}) {
  return (
    <section className="evac-step evac-step-choice">
      <div className="evac-content-group">
        <div className="evac-intro">
          <h1>{copy?.choiceTitle ?? '어떻게 도와드릴까요?'}</h1>
          <p className="evac-lead">{copy?.choiceBody ?? '필요한 도움을 선택해주세요.'}</p>
        </div>

        {failure}

        <div className="evac-choice-list">
          <button
            className={`evac-card evac-choice${selected === 'help' ? ' selected' : ''
              }`}
            type="button"
            disabled={pending}
            onClick={() => onChoose('help')}
          >
            <span className="evac-choice-icon accent" aria-hidden="true">
              🤝
            </span>
            <span>
              <strong>{copy?.help ?? '도움이 필요해요'}</strong>
              <small>{copy?.helpBody ?? '보호자 또는 119에 연락할 수 있도록 안내합니다'}</small>
            </span>
            <b aria-hidden="true">›</b>
          </button>

          <button
            className={`evac-card evac-choice${selected === 'self' ? ' selected' : ''
              }`}
            type="button"
            disabled={pending}
            onClick={() => onChoose('self')}
          >
            <span className="evac-choice-icon" aria-hidden="true">
              🚶
            </span>
            <span>
              <strong>{copy?.direct ?? '혼자서 대피할게요'}</strong>
              <small>{copy?.directBody ?? '안전 필터를 거친 대피 경로를 안내합니다'}</small>
            </span>
            <b aria-hidden="true">›</b>
          </button>
        </div>
      </div>

      <OfficialNotice />
    </section>
  )
}

function HelpRequestStep({
  guardian,
  onHome,
  copy,
  onCall119,
}: {
  guardian: Guardian | null
  onHome: () => void
  copy?: FlowCopy
  onCall119?: () => void
}) {
  // Guardian.phone is a required contract field, but a defensively-empty
  // string should hide the button the same way a null guardian does —
  // never render it disabled.
  const guardianPhone = guardian !== null && guardian.phone.trim() !== '' ? guardian.phone : null
  return (
    <section className="evac-step evac-step-centered evac-success">
      <div className="evac-content-group">
        <div className="evac-step-main">
          <div className="evac-check">✓</div>
          <h1>{copy?.helpTitle ?? '어떤 도움이 필요하세요?'}</h1>
          <p>{copy?.helpPrompt ?? '연락할 곳을 선택해주세요.'}</p>
        </div>
        <StepFooter>
          {/* Both contact routes carry equal weight — neither is the
              "more correct" one, so both render as the same blue primary
              button. Only 처음으로 below stays the outline secondary. */}
          <div className="evac-help-contacts">
            {guardianPhone !== null && (
              <a className="evac-primary" href={`tel:${guardianPhone}`}>{copy?.guardian ?? '👤 보호자에게 연락하기'}</a>
            )}
            <a className="evac-primary" href="tel:119" onClick={onCall119}>{copy?.call119 ?? '🚨 119에 연락하기'}</a>
          </div>
          <button className="evac-secondary" type="button" onClick={onHome}>{copy?.backHome ?? '처음으로'}</button>
        </StepFooter>
      </div>
    </section>
  )
}

function EvacuationLevels({ stage = 3 }: { stage?: 1 | 2 | 3 }) {
  const vi = useContext(FlowCopyContext) === FLOW_COPY.vi
  const labels = vi
    ? [['Theo dõi', 'Kiểm tra'], ['Chuẩn bị', 'Chuẩn bị đồ'], ['Sơ tán ngay', 'Hướng dẫn']]
    : [['상황 주시', '정보 확인'], ['대피 준비', '용품 준비'], ['즉시 대피', '대피 안내']]
  return <div className="evac-levels" aria-label={vi ? 'Mức sơ tán' : '대피 단계'}>{labels.map(([label, detail], index) => {
    const value = (index + 1) as 1 | 2 | 3
    return <div key={label} className={stage === value ? 'active' : ''}><i />{label}<small>{stage === value ? (vi ? 'Mức hiện tại' : '현재 단계') : detail}</small></div>
  })}</div>
}

function ShelterRecommendationStep({
  onNext,
  stage,
  stageLabel,
  stageAction,
  shelterState,
  pending = false,
  failure,
  nextAction,
  demoShelter,
  demoAlert,
}: {
  onNext: () => void
  stage?: 1 | 2 | 3
  stageLabel?: string
  stageAction?: string
  shelterState?: { loading: boolean; error: string | null; result: ShelterList | null }
  pending?: boolean
  failure?: ReactNode
  nextAction?: string
  demoShelter?: EvacuationDemoData['shelter']
  demoAlert?: EvacuationDemoData['alert']
}) {
  const production = shelterState !== undefined
  const shelter = shelterState?.result?.items[0] ?? null
  const excludedCount = shelterState?.result?.excluded.reduce((sum, item) => sum + item.count, 0) ?? 0
  const vi = useContext(FlowCopyContext) === FLOW_COPY.vi
  const lang: Language = vi ? 'vi' : 'ko'
  // Reuses ShelterGuide's already-approved copy (shelter.degradedNotice /
  // shelter.allExcluded.* / shelter.excludedPrefix / shelter.cacheAsOf) —
  // no new safety-adjacent wording is authored here. See components/
  // ShelterGuide.tsx for the source of each key and its safety meaning.
  const productionNote = (() => {
    const result = shelterState?.result
    if (result == null) return ''
    const note = result.availability === 'upstream_unavailable'
      ? t('shelter.degradedNotice', lang)
      : result.availability === 'all_excluded'
        ? (excludedCount > 0
            ? t('shelter.allExcluded.why', lang, { count: excludedCount, reasons: summarizeShelterExclusions(result.excluded, lang) })
            : t('shelter.allExcluded.whyNone', lang))
        : excludedCount > 0
          ? `${t('shelter.excludedPrefix', lang, { count: excludedCount })} (${summarizeShelterExclusions(result.excluded, lang)})`
          : ''
    if (result.dataAsOf === null) return note
    const cacheNote = t('shelter.cacheAsOf', lang, { when: new Date(result.dataAsOf).toLocaleString(vi ? 'vi-VN' : 'ko-KR') })
    return note === '' ? cacheNote : `${note} · ${cacheNote}`
  })()
  return (
    <section className="evac-step evac-step-distributed">
      <div className="evac-content-group">
        <div className="evac-shelter-intro">
          <EvacuationLevels stage={stage} />
          <h1>
            {production
              ? <>{vi ? 'Hiện tại: ' : '지금은 '}<em>「{stageLabel}」</em></>
              : <>지금은 <em>「즉시 대피」</em></>}
            <br />
            {production ? stageAction : '여기로 가세요'}
          </h1>
        </div>

        <div className="evac-shelter-body">
          {production && shelterState.loading && <article className="evac-card evac-shelter"><h2>{t('shelter.searching', lang)}</h2></article>}
          {production && shelterState.error !== null && <article className="evac-card evac-shelter" role="alert"><h2>{t('shelter.fetchFailedPrefix', lang)}</h2><p>{shelterState.error}</p></article>}
          {production && !shelterState.loading && shelterState.error === null && shelter === null && <article className="evac-card evac-shelter"><h2>{t('shelter.emptyList', lang)}</h2>{nextAction !== undefined && <strong className="evac-distance">{nextAction}</strong>}</article>}
          {(!production || shelter !== null) && <article className="evac-card evac-shelter">
            {production && shelter !== null ? <ProductionShelterCard shelter={shelter} /> : <>
            <h2>{demoShelter?.name}</h2>
            <p>
              {demoShelter?.address} · {demoShelter?.type}
            </p>

            <div className="evac-tags">
              {demoShelter?.tags.map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
            </div>

            {/* v0.9 (ADR-0016): cautions:[]면 아무것도 렌더하지 않는다 —
                기존 카드와 완전히 동일. 값이 있을 때만 작은 chip 행을
                기존 태그 바로 아래에 추가한다(별도 카드/모달/섹션 없음). */}
            {(demoShelter?.cautions.length ?? 0) > 0 && (
              <div className="evac-cautions">
                {demoShelter?.cautions.map((caution) => (
                  <span key={caution}>{CAUTION_LABEL[caution]}</span>
                ))}
              </div>
            )}

            <strong className="evac-distance">
              <b>{demoShelter?.minutes}</b>분 · 침수 회피 경로{' '}
              {demoShelter?.distance}
            </strong>

            <div className="evac-deadline">
              <span>
                출입 권고 마감
                <b>{demoShelter?.recommendationDeadline}</b>
              </span>
              <span>
                남은 시간
                <b>{demoShelter?.minutesRemaining}분</b>
              </span>
            </div>
            </>}
          </article>}

          <p className="evac-route-note">
            {production
              ? productionNote
              : <>지하 주차장 2곳 제외 · {demoAlert?.source}</>}
          </p>
        </div>

        <StepFooter>
          {failure}
          <button className="evac-primary" type="button" disabled={pending || (production && shelter === null)} onClick={onNext}>{vi ? 'Xem đường đi' : '경로 보기'}</button>
        </StepFooter>
      </div>
    </section>
  )
}

// Reuses the same reason-label vocabulary and separator ShelterGuide's
// AllExcludedNotice/excludedPrefix banners already use (excludedReasonLabel,
// countUnit, shelter.allExcluded.reasonSeparator) — ExcludedReason only has
// 3 possible values, so no truncation/"tail others" bucket is needed here.
function summarizeShelterExclusions(excluded: ShelterExclusion[], lang: Language): string {
  const sep = t('shelter.allExcluded.reasonSeparator', lang)
  return excluded.map((e) => `${excludedReasonLabel(e.reason, lang)} ${e.count}${countUnit(lang)}`).join(sep)
}

function formatShelterDistance(shelter: Shelter): string {
  return shelter.distanceM >= 1000
    ? `${(shelter.distanceM / 1000).toFixed(1)}km`
    : `${Math.round(shelter.distanceM)}m`
}

function formatShelterBearing(shelter: Shelter, vi: boolean): string | null {
  return shelter.bearing == null ? null : ({
    N: vi ? 'Bắc' : '북쪽', NE: vi ? 'Đông Bắc' : '북동쪽', E: vi ? 'Đông' : '동쪽',
    SE: vi ? 'Đông Nam' : '남동쪽', S: vi ? 'Nam' : '남쪽', SW: vi ? 'Tây Nam' : '남서쪽',
    W: vi ? 'Tây' : '서쪽', NW: vi ? 'Tây Bắc' : '북서쪽',
  } as const)[shelter.bearing]
}

function ProductionShelterCard({ shelter }: { shelter: Shelter }) {
  const vi = useContext(FlowCopyContext) === FLOW_COPY.vi
  const distance = formatShelterDistance(shelter)
  const bearing = formatShelterBearing(shelter, vi)
  return <>
    <h2>{shelter.name}</h2>
    <p>{shelter.address}{bearing === null ? '' : ` · ${bearing}`}</p>
    {shelter.capacity != null && <div className="evac-tags"><span>{vi ? `Sức chứa ${shelter.capacity} người` : `수용 ${shelter.capacity}명`}</span></div>}
    {shelter.cautions.length > 0 && <div className="evac-cautions">
      {shelter.cautions.map((caution) => <span key={caution}>{vi
        ? (caution === 'stairs' ? 'Chú ý cầu thang' : 'Chú ý thời gian di chuyển')
        : CAUTION_LABEL[caution]}</span>)}
    </div>}
    <strong className="evac-distance">{vi ? 'Khoảng cách ' : '거리 '}<b>{distance}</b></strong>
  </>
}

function RouteGuidanceStep({
  onArrival,
  production = false,
  shelter = null,
  pending = false,
  failure,
  copy,
  stageLabel,
  demoRoute,
}: {
  onArrival: () => void
  production?: boolean
  shelter?: Shelter | null
  pending?: boolean
  failure?: ReactNode
  copy?: FlowCopy
  stageLabel?: string
  demoRoute?: EvacuationDemoData['route']
}) {
  const vi = copy === FLOW_COPY.vi
  const bearing = shelter === null ? null : formatShelterBearing(shelter, vi)
  const distance = shelter === null ? null : formatShelterDistance(shelter)
  return (
    <section className="evac-step evac-step-distributed evac-route-step">
      <div className="evac-content-group">
        <div className="evac-route-intro">
          <h1>{copy?.routeTitle ?? '이 길로 가세요'}</h1>
          <p className="evac-lead">
            {production
              ? (vi ? `Giai đoạn hiện tại là ${stageLabel}. Hãy kiểm tra nơi trú ẩn được đề xuất.` : `현재 ${stageLabel} 단계입니다. 추천 대피소를 확인하세요.`)
              : <>가장 짧은 길은 차단 구간 {demoRoute?.blockedSegments}곳을 지나므로 사용하지 않습니다.</>}
          </p>
        </div>

        <div className="evac-route-body">
          <div
            className="evac-map"
            role="img"
            aria-label={vi ? 'Sơ đồ minh họa tránh khu vực ngập đến nơi trú ẩn' : '현재 위치에서 대피소까지 침수 구역을 피하는 예시 경로'}
          >
            <div className="flood-zone">{vi ? 'Khu vực dự kiến ngập' : '침수예상구역'}</div>
            <div className="safe-line line-a" />
            <div className="safe-line line-b" />
            <div className="safe-line line-c" />
            <div className="short-line" />

            <span className="map-label start">{vi ? 'Vị trí hiện tại' : '현재 위치'}</span>
            <span className="map-label end">{vi ? 'Nơi trú ẩn' : '추천 대피소'}</span>

            <span className="blocked b1">×</span>
            <span className="blocked b2">×</span>
            <span className="blocked b3">×</span>
          </div>

          <div className="evac-route-stats">
            <div className="active">
              {production ? (vi ? 'Nơi trú ẩn đề xuất' : '추천 대피소') : '안내 · 침수 회피'}
              <strong>
                {production
                  ? (shelter === null ? '' : `${shelter.name} · ${shelter.address}`)
                  : <>{demoRoute?.avoidedDistance} · {demoRoute?.avoidedMinutes}분</>}
              </strong>
            </div>

            <div>
              {production ? (vi ? 'Khoảng cách · hướng' : '거리 · 방향') : '최단 · 미사용'}
              <strong>{production ? [distance, bearing].filter(Boolean).join(' · ') : demoRoute?.unusedShortestDistance}</strong>
            </div>
          </div>

          <div className="evac-legend">
            <span>
              <i className="safe" />
              {vi ? 'Đường tránh ngập' : '회피 경로'}
            </span>
            <span>
              <i className="short" />
              {vi ? 'Đường ngắn nhất không dùng' : '미사용 최단 경로'}
            </span>
            <span>
              <i className="water" />
              {vi ? 'Khu vực dự kiến ngập' : '침수예상구역'}
            </span>
            <span>
              <i className="block" />
              {vi ? 'Đoạn đường bị chặn' : '차단 구간'}
            </span>
          </div>

          <p className="evac-user-note">
            {copy === FLOW_COPY.vi
              ? 'Nút hoàn tất là do người dùng trực tiếp chọn, không phải xác nhận bằng GPS.'
              : '도착 완료는 GPS 확인이 아니라 사용자가 직접 표시하는 버튼입니다.'}
          </p>
        </div>

        <StepFooter>
          {failure}
          <button className="evac-primary" type="button" disabled={pending} onClick={onArrival}>{copy?.arrival ?? '도착 완료'}</button>
        </StepFooter>
      </div>
    </section>
  )
}

function ArrivalCompleteStep({ onHome, copy }: { onHome: () => void; copy?: FlowCopy }) {
  const vi = copy === FLOW_COPY.vi
  return <section className="evac-step evac-step-centered evac-success"><div className="evac-content-group"><div className="evac-step-main"><div className="evac-check">✓</div><h1>{copy?.arrivalTitle ?? <>도착 완료로<br /><em>표시했습니다.</em></>}</h1><p>{copy?.arrivalBody ?? '필요한 경우 재난문자와 공식 안내를 계속 확인해주세요.'}</p><div className="evac-card evac-user-confirmed"><strong>{vi ? 'Bản ghi do người dùng trực tiếp chọn' : '사용자가 직접 누른 기록'}</strong><span>{vi ? 'Không xác định việc đến nơi bằng GPS.' : 'GPS로 도착을 판정하지 않았습니다.'}</span></div></div><StepFooter><button className="evac-secondary" type="button" onClick={onHome}>{copy?.backHome ?? '처음으로'}</button></StepFooter></div></section>
}

function ActionFailureView({ copy, retry, continueWithoutRecord, continueLabel }: {
  copy: FlowCopy
  retry?: () => void
  continueWithoutRecord?: () => void
  continueLabel?: string
}) {
  return <div className="evac-card evac-shelter" role="alert">
    <strong className="evac-distance">{copy.failure}</strong>
    <div className="evac-help-contacts">
      {retry !== undefined && <button className="evac-primary" type="button" onClick={retry}>{copy.retry}</button>}
      {continueWithoutRecord !== undefined && <button className="evac-secondary" type="button" onClick={continueWithoutRecord}>
        {continueLabel ?? copy.continuingShelter}
      </button>}
    </div>
  </div>
}
