/** 下载文件名取服务端 Content-Disposition（trip-v{版本}.ics）；缺失或不合规时退回 trip.ics。 */
export function icsFilename(disposition: string | null): string {
  const name = disposition?.match(/filename="([^"]+)"/)?.[1];
  return name && /^[\w.-]+\.ics$/.test(name) ? name : "trip.ics";
}
