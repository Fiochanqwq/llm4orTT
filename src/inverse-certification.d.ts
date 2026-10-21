import type { ReactElement } from 'react';
export function inverseCertificationInput(props: {
  draft: string; disabled: boolean; update: (value: string) => void;
}): ReactElement | null;
export function inverseCertificationReport(props: {
  analysis: { compatibility?: Record<string, unknown>; supersededByModelProposal?: boolean };
}): ReactElement | null;
