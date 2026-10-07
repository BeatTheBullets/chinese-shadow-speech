// The Brave bookmarklet (addendum §3): opens this app's library with the page the user is on, which asks before adding it.
export function bookmarkletCode(origin: string): string {
  return `javascript:location.href='${origin}/library?add='+encodeURIComponent(location.href)`
}

// The question asked when the library opens with ?add=<url> (an optional &title= is shown instead of the link).
export function addQuestion(url: string, title?: string | null): string {
  return `Add ${title?.trim() || url} to shadow-speech?`
}
