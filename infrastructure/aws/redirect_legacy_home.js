function handler(event) {
    const request = event.request;
    const isLegacyHome = /^\/assets\/(?:releases\/[a-f0-9]{40}\/)?command-center\/index\.html$/.test(request.uri);

    if (isLegacyHome && (request.method === "GET" || request.method === "HEAD")) {
        return {
            statusCode: 301,
            statusDescription: "Moved Permanently",
            headers: {
                location: { value: "/" },
                "cache-control": { value: "public, max-age=300" },
            },
        };
    }

    return request;
}
