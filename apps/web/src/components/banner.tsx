/** One alert shape for errors, warnings and notices; children are plain text or buttons. */
export function Banner({
  kind,
  children,
}: {
  kind: "error" | "warning" | "info";
  children: React.ReactNode;
}) {
  return (
    <div className={`banner banner-${kind}`} role="alert">
      {children}
    </div>
  );
}
