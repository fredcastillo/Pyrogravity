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

    // The same index owns the versioned assets for the home and study routes.
    if ((request.method === "GET" || request.method === "HEAD") &&
        /^\/estudios\/[a-z0-9]+(?:-[a-z0-9]+)*\/?$/.test(request.uri)) {
        request.uri = "/index.html";
    }

    return request;
}
