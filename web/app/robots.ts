import type { MetadataRoute } from "next";

const SITE_URL = process.env.SITE_URL ?? "http://localhost:3000";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Private/internal surfaces and the BFF proxy stay out of the index.
      disallow: ["/evaluations", "/ask", "/api/"],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
