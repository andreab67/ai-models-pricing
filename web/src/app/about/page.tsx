export default function AboutPage() {
  return (
    <article className="card rounded-lg p-5 prose prose-sm max-w-none dark:prose-invert">
      <h1>About</h1>
      <p>
        This dashboard polls OpenRouter&apos;s public <code>/api/v1/models</code>{" "}
        endpoint every 15 minutes, normalizes per-token pricing to USD per 1M
        tokens, and overlays Kilo Code&apos;s plan math. The Top-10 ranking
        applies a coding-biased weight (30% input, 70% output) and filters for
        tool-calling support and ≥64k context.
      </p>
      <h2>Channels</h2>
      <ul>
        <li><strong>OpenRouter PAYG</strong> — list rate + 5.5% credit purchase fee.</li>
        <li><strong>OpenRouter BYOK</strong> — list rate + 5% after 1M req/mo.</li>
        <li><strong>Kilo Pass</strong> — list rate × (1 − discount), where discount is derived from your tier and subscription streak.</li>
        <li><strong>Kilo BYOK</strong> — true passthrough.</li>
      </ul>
      <h2>Stack</h2>
      <ul>
        <li>Backend: FastAPI + SQLAlchemy 2 + Redis + Postgres.</li>
        <li>Frontend: Next.js 14 App Router + Tailwind + Recharts.</li>
        <li>Schedules: Kubernetes CronJobs (pricing refresh, daily email, Kilo page diff).</li>
        <li>Deployed on k8s-home behind Traefik + cert-manager.</li>
      </ul>
    </article>
  );
}
