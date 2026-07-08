import type { MetadataRoute } from "next";
import { listDocuments } from "@/lib/api/documents";

export const dynamic = "force-dynamic";

const SITE_URL = process.env.SITE_URL ?? "http://localhost:3000";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/lawyers`, changeFrequency: "daily", priority: 0.8 },
    { url: `${SITE_URL}/documents`, changeFrequency: "weekly", priority: 0.8 },
  ];

  // Real, public document URLs — never fabricated entries. Degrade to the
  // static routes if the API is unavailable at generation time.
  try {
    const documents = await listDocuments();
    for (const doc of documents) {
      staticRoutes.push({
        url: `${SITE_URL}/documents/${encodeURIComponent(doc.document_id)}`,
        changeFrequency: "monthly",
        priority: 0.6,
      });
    }
  } catch {
    // ignore — return static routes only
  }
  return staticRoutes;
}
