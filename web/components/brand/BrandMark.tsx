export function BrandMark({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`r2m-mark ${className}`}
      viewBox="0 0 340 150"
      role="img"
      aria-label="R2M — Responsibility to Monitoring"
    >
      <text
        x="18"
        y="122"
        fontFamily="Georgia, 'Times New Roman', serif"
        fontSize="112"
        fill="currentColor"
      >
        R
      </text>
      <path
        className="r2m-mark-accent"
        d="M120 46H151M135 46V120M120 120H151M163 46H194M178 46V120M163 120H194"
        fill="none"
        stroke="#a6cf3d"
        strokeWidth="8"
      />
      <text
        x="207"
        y="122"
        fontFamily="Georgia, 'Times New Roman', serif"
        fontSize="112"
        fill="currentColor"
      >
        M
      </text>
    </svg>
  );
}
