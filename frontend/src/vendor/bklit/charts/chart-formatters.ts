// Local adaptation: chart labels follow the app locale and the usage API's UTC buckets.
function dateFormatter(options: Intl.DateTimeFormatOptions) {
  const cache = new Map<string, Intl.DateTimeFormat>();
  return { format(value: Date | number) {
    const locale = typeof document === "undefined" ? "en" : document.documentElement.lang || "en";
    let formatter = cache.get(locale);
    if (!formatter) {
      formatter = new Intl.DateTimeFormat(locale, { ...options, timeZone: "UTC" });
      cache.set(locale, formatter);
    }
    return formatter.format(value);
  } };
}
export const shortDateFmt = dateFormatter({ month: "short", day: "numeric" });
export const weekdayDateFmt = dateFormatter({ weekday: "short", month: "short", day: "numeric" });
export const hmsTimeFmt = dateFormatter({ hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
export const intFmt = new Intl.NumberFormat("en-US").format;
