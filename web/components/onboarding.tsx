"use client";

const features = [
  {
    title: "Save anything, effortlessly",
    body: "Add any article, post, tweet, image, text, or link to Re:Me. It is saved instantly, then processed in the background—summarized, understood, connected to your existing memories, and automatically organized into relevant categories.",
  },
  {
    title: "Turn saved content into action",
    body: "Re:Me identifies what you can do next and suggests the right action:",
    bullets: [
      "Event → Add to calendar or set a reminder",
      "Offer → Notify before it expires",
      "Place → Save to a map or suggest it when relevant",
      "Opportunity → Track the deadline",
      "Job post → Draft an application email and ask you to review it",
      "Resource or idea → Add it to a project, list, or plan",
    ],
  },
  {
    title: "Surface the right memory at the right moment",
    body: "With the user's permission, Re:Me understands the context of the webpage currently being viewed. If it matches something previously saved, Re:Me gently surfaces related notes, useful links, or an unfinished action—without interrupting the browsing experience.",
  },
  {
    title: "Go beyond what you saved",
    body: "Re:Me can research beyond your existing memories to find similar places, related articles, updated information, upcoming events, new opportunities, or better alternatives. It clearly distinguishes between content you saved and new recommendations it discovered, helping your knowledge stay current and useful.",
  },
];

export function Onboarding({email, onDone}: {email: string; onDone: () => void}) {
  return (
    <div className="onboarding" role="dialog" aria-modal="true" aria-labelledby="onboarding-title">
      <header className="onboarding-header">
        <div className="brand"><span>Re</span>:Me</div>
        <span className="onboarding-you">Welcome, {email}</span>
      </header>
      <main className="onboarding-main">
        <div className="eyebrow">FOUR THINGS RE:ME CAN DO FOR YOU</div>
        <h1 id="onboarding-title">Keep it. Act on it. Find it again.</h1>
        <div className="onboarding-grid">
          {features.map(feature => (
            <section className="onboarding-card" key={feature.title}>
              <h2>{feature.title}</h2>
              <p>{feature.body}</p>
              {feature.bullets && <ul>{feature.bullets.map(item => <li key={item}>{item}</li>)}</ul>}
            </section>
          ))}
        </div>
        <button className="primary onboarding-cta" onClick={onDone}>Start remembering</button>
        <small className="onboarding-note">Everything you save is private to your account.</small>
      </main>
    </div>
  );
}