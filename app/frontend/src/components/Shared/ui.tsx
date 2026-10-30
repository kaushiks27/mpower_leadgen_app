// Tiny shared primitives so every form looks consistent. Plain English, no i18n.

export function Field(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={
        "w-full px-4 py-3 rounded-xl border border-ink/15 font-body text-ink " +
        "placeholder:text-ink/30 focus:outline-none focus:ring-2 " +
        "focus:ring-mpower-orange/30 focus:border-mpower-orange btn-press " +
        (props.className ?? "")
      }
    />
  );
}

export function PrimaryButton(
  props: React.ButtonHTMLAttributes<HTMLButtonElement>,
) {
  return (
    <button
      {...props}
      className={
        "w-full py-3 bg-mpower-orange text-white font-heading font-semibold " +
        "rounded-xl hover:bg-mpower-orange/90 btn-press disabled:opacity-50 " +
        (props.className ?? "")
      }
    />
  );
}

export function ErrorText({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-err-red text-sm font-body text-center" role="alert">
      {children}
    </p>
  );
}

export function OkText({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-ok-green text-sm font-body text-center">{children}</p>
  );
}
