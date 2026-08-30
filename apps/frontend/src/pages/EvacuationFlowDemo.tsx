import { mockAlert, mockGuardian, mockProfile, mockRoute, mockShelter } from '../mocks/evacuation'
import { speechScripts } from '../mocks/evacuationSpeech'
import { EvacuationFlow as EvacuationFlowPresentation } from './EvacuationFlow'

export function EvacuationFlow() {
  return <EvacuationFlowPresentation demo={{
    alert: mockAlert,
    guardian: mockGuardian,
    preregistered: mockProfile.preregistered,
    shelter: mockShelter,
    route: mockRoute,
    speech: speechScripts,
  }} />
}
