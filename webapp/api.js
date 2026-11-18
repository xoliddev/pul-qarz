// HTTP client for the Mini App API. Every request carries Telegram's signed initData; the server checks it.
export function httpApi(initData) {
  async function call(method, path, body) {
    let res;
    try {
      res = await fetch(path, {
        method,
        headers: { Authorization: `tma ${initData}`, 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw Object.assign(new Error('offline'), { code: 'offline' });
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(data.error ?? 'generic'), { code: data.error ?? 'generic' });
    return data;
  }
  return {
    me: () => call('GET', '/api/me'),
    person: (uid) => call('GET', `/api/people/${Number(uid)}`),
    create: (body) => call('POST', '/api/debts', body),
    answer: (uid, body) => call('POST', `/api/people/${Number(uid)}/answer`, body),
    change: (uid, body) => call('POST', `/api/people/${Number(uid)}/changes`, body),
    setLang: (lang) => call('POST', '/api/lang', { lang }),
  };
}
