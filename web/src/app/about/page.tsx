export default function AboutPage() {
  return (
    <article className="card rounded-lg p-5 prose prose-sm max-w-none dark:prose-invert">
      <h1>About This Project</h1>
      <p>
        This dashboard demonstrates full-stack expertise in AI operations and cost optimization across multiple LLM providers.
        It automatically tracks real-time pricing updates, normalizes costs across OpenRouter, OpenAI, Anthropic, and other providers,
        and applies sophisticated economic analysis to help teams optimize their AI infrastructure spend.
      </p>

      <h2>What It Does</h2>
      <p>
        The dashboard ingests live pricing data every 15 minutes, normalizes per-token rates across different provider models
        into USD per 1M tokens for easy comparison, and surfaces intelligent rankings that account for both cost and capability
        (context window, tool support, modality support). Account balance tracking and activity feeds integrate with multiple
        provider APIs to give teams a centralized view of their AI spending and usage patterns.
      </p>

      <h2>Why It Matters</h2>
      <p>
        Organizations using multiple LLM providers lack a unified view of costs and capabilities. This tool solves that by:
      </p>
      <ul>
        <li>Centralizing pricing data across OpenRouter, OpenAI, Anthropic, and more into a single source of truth</li>
        <li>Automating cost tracking and eliminating manual spreadsheet maintenance</li>
        <li>Enabling data-driven model selection based on real-time pricing and capability analysis</li>
        <li>Exposing hidden costs in pricing structures (credits, tiering, discounts) for accurate budget planning</li>
      </ul>

      <h2>Technical Highlights</h2>
      <ul>
        <li><strong>Backend:</strong> FastAPI + SQLAlchemy 2 + Redis caching + Postgres for robust data persistence and performance</li>
        <li><strong>Frontend:</strong> Next.js 14 App Router + Tailwind CSS + Recharts for responsive, data-rich visualizations</li>
        <li><strong>Infrastructure:</strong> Kubernetes with CronJobs for scheduled refreshes, Traefik ingress, cert-manager TLS</li>
        <li><strong>Multi-Provider Integration:</strong> Concurrent API calls with retry logic, cost normalization, and real-time balance tracking</li>
      </ul>

      <h2>Consulting & Custom Builds</h2>
      <p>
        If you need similar infrastructure for your organization—whether it&apos;s custom cost tracking, multi-provider orchestration,
        or operational dashboards for AI systems—this project demonstrates the technical depth available. Available for C2C consulting
        on full-stack AI systems, cost optimization tools, and LLM infrastructure projects.
      </p>
    </article>
  );
}
