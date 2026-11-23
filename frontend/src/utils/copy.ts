export async function copyText(text: string): Promise<boolean> {
  if (!text) return false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fallback below
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    ta.style.top = "-9999px";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

export function formatCompactNumber(num: number): string {
  if (num >= 100_000_000) return `${(num / 100_000_000).toFixed(2)}亿`;
  if (num >= 10_000) return `${(num / 10_000).toFixed(1)}万`;
  return num.toLocaleString("zh-CN");
}
