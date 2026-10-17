export function Saturn({ size = 32, className = '' }: { size?: number; className?: string }) {
  return <img className={'saturn ' + className} src="/saturn.svg" width={size} height={size} alt="Saturn Logo" draggable={false}/>;
}
