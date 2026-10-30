const BRAND = process.env.NEXT_PUBLIC_BRAND_NAME ?? "SalesPath by BuLoop AI";

// Centered auth card used by login / activate / forgot / reset. Clean Light
// Industrial: cream canvas, white card, mPower-orange logo tile.
export default function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <main className="min-h-screen flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="flex items-center gap-2.5 justify-center mb-8">
          <div className="w-9 h-9 bg-mpower-orange rounded-lg flex items-center justify-center">
            <span className="font-heading font-bold text-white text-sm">
              {(BRAND[0] ?? "M").toUpperCase()}
            </span>
          </div>
          <span className="font-heading font-bold text-ink text-lg tracking-tight">
            {BRAND}
          </span>
        </div>
        <div className="bg-surface border border-ink/10 rounded-2xl shadow-sm p-8">
          <h1 className="font-heading text-xl font-semibold text-ink text-center">
            {title}
          </h1>
          {subtitle && (
            <p className="text-sm text-ink/50 text-center mt-1.5 mb-6">{subtitle}</p>
          )}
          {!subtitle && <div className="mb-6" />}
          {children}
        </div>
      </div>
    </main>
  );
}
