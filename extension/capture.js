// Executed only by an explicit capture or an enabled Context Mode observation.
function readPage() {
  const article = document.querySelector("article") || document.querySelector("main") || document.querySelector('[role="main"]');
  const content = article ? article.cloneNode(true) : null;
  if (content) content.querySelectorAll("script,style,nav,footer,aside,noscript,form").forEach(node => node.remove());
  const meta = selector => document.querySelector(selector)?.content || "";
  let image = meta('meta[property="og:image"]') || meta('meta[name="twitter:image"]');
  if (!image) {
    const candidates = [...(article || document).querySelectorAll("img")];
    const lead = candidates.find(img => img.naturalWidth >= 240 && img.naturalHeight >= 120);
    image = lead?.currentSrc || lead?.src || "";
  }
  let imageUrl = null;
  try { const url = new URL(image, location.href); if (image && /^https?:$/.test(url.protocol)) imageUrl = url.href; } catch {}
  return {source_url: location.href, page_title: document.title.slice(0,500),
    image_url: imageUrl,
    meta_description: (meta('meta[name="description"]') || meta('meta[property="og:description"]')).slice(0,2000),
    headings: [...document.querySelectorAll("h1,h2,h3")].slice(0,20).map(e => (e.innerText || "").slice(0,300)),
    selected_text: getSelection()?.toString().slice(0,8000) || null,
    visible_text: (content?.innerText || content?.textContent || document.body?.innerText || "").slice(0,16000),
    captured_at: new Date().toISOString()};
}
readPage();
