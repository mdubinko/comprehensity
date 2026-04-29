# Clone Source Report

Blueprint: `output/tier2/requests/blueprint_semantic_20260425_173207.json`  
Repository: `/Users/micah/.comprehensity/tier2-repos/requests`  
Clone blocks: 12

| Clone | Kind | Lines | Instances |
|-------|------|------:|----------:|
| dup_7 | approximate | 15 | 3 |
| dup_10 | approximate | 12 | 3 |
| dup_11 | approximate | 10 | 2 |
| dup_4 | approximate | 9 | 2 |
| dup_1 | approximate | 8 | 2 |
| dup_0 | approximate | 7 | 2 |
| dup_2 | approximate | 7 | 3 |
| dup_3 | approximate | 7 | 2 |
| dup_5 | approximate | 6 | 3 |
| dup_6 | approximate | 6 | 2 |
| dup_8 | approximate | 6 | 2 |
| dup_9 | approximate | 5 | 2 |

## dup_7 — approximate, 15 lines, 3 instances

### `tests/test_requests.py` lines 1321–1335

```py
    def test_cookie_as_dict_keys(self):
        key = "some_cookie"
        value = "some_value"

        key1 = "some_cookie1"
        value1 = "some_value1"

        jar = requests.cookies.RequestsCookieJar()
        jar.set(key, value)
        jar.set(key1, value1)

        keys = jar.keys()
        assert keys == list(keys)
        # make sure one can use keys multiple times
        assert list(keys) == list(keys)
```

### `tests/test_requests.py` lines 1337–1351

```py
    def test_cookie_as_dict_values(self):
        key = "some_cookie"
        value = "some_value"

        key1 = "some_cookie1"
        value1 = "some_value1"

        jar = requests.cookies.RequestsCookieJar()
        jar.set(key, value)
        jar.set(key1, value1)

        values = jar.values()
        assert values == list(values)
        # make sure one can use values multiple times
        assert list(values) == list(values)
```

### `tests/test_requests.py` lines 1353–1367

```py
    def test_cookie_as_dict_items(self):
        key = "some_cookie"
        value = "some_value"

        key1 = "some_cookie1"
        value1 = "some_value1"

        jar = requests.cookies.RequestsCookieJar()
        jar.set(key, value)
        jar.set(key1, value1)

        items = jar.items()
        assert items == list(items)
        # make sure one can use items multiple times
        assert list(items) == list(items)
```

## dup_10 — approximate, 12 lines, 3 instances

### `src/requests/api.py` lines 62–73

```py
def get(url, params=None, **kwargs):
    r"""Sends a GET request.

    :param url: URL for the new :class:`Request` object.
    :param params: (optional) Dictionary, list of tuples or bytes to send
        in the query string for the :class:`Request`.
    :param \*\*kwargs: Optional arguments that ``request`` takes.
    :return: :class:`Response <Response>` object
    :rtype: requests.Response
    """

    return request("get", url, params=params, **kwargs)
```

### `src/requests/api.py` lines 118–130

```py
def put(url, data=None, **kwargs):
    r"""Sends a PUT request.

    :param url: URL for the new :class:`Request` object.
    :param data: (optional) Dictionary, list of tuples, bytes, or file-like
        object to send in the body of the :class:`Request`.
    :param json: (optional) A JSON serializable Python object to send in the body of the :class:`Request`.
    :param \*\*kwargs: Optional arguments that ``request`` takes.
    :return: :class:`Response <Response>` object
    :rtype: requests.Response
    """

    return request("put", url, data=data, **kwargs)
```

### `src/requests/api.py` lines 133–145

```py
def patch(url, data=None, **kwargs):
    r"""Sends a PATCH request.

    :param url: URL for the new :class:`Request` object.
    :param data: (optional) Dictionary, list of tuples, bytes, or file-like
        object to send in the body of the :class:`Request`.
    :param json: (optional) A JSON serializable Python object to send in the body of the :class:`Request`.
    :param \*\*kwargs: Optional arguments that ``request`` takes.
    :return: :class:`Response <Response>` object
    :rtype: requests.Response
    """

    return request("patch", url, data=data, **kwargs)
```

## dup_11 — approximate, 10 lines, 2 instances

### `src/requests/api.py` lines 76–85

```py
def options(url, **kwargs):
    r"""Sends an OPTIONS request.

    :param url: URL for the new :class:`Request` object.
    :param \*\*kwargs: Optional arguments that ``request`` takes.
    :return: :class:`Response <Response>` object
    :rtype: requests.Response
    """

    return request("options", url, **kwargs)
```

### `src/requests/api.py` lines 148–157

```py
def delete(url, **kwargs):
    r"""Sends a DELETE request.

    :param url: URL for the new :class:`Request` object.
    :param \*\*kwargs: Optional arguments that ``request`` takes.
    :return: :class:`Response <Response>` object
    :rtype: requests.Response
    """

    return request("delete", url, **kwargs)
```

## dup_4 — approximate, 9 lines, 2 instances

### `src/requests/models.py` lines 732–740

```py
    def __bool__(self):
        """Returns True if :attr:`status_code` is less than 400.

        This attribute checks if the status code of the response is between
        400 and 600 to see if there was a client error or a server error. If
        the status code, is between 200 and 400, this will return True. This
        is **not** a check to see if the response code is ``200 OK``.
        """
        return self.ok
```

### `src/requests/models.py` lines 742–750

```py
    def __nonzero__(self):
        """Returns True if :attr:`status_code` is less than 400.

        This attribute checks if the status code of the response is between
        400 and 600 to see if there was a client error or a server error. If
        the status code, is between 200 and 400, this will return True. This
        is **not** a check to see if the response code is ``200 OK``.
        """
        return self.ok
```

## dup_1 — approximate, 8 lines, 2 instances

### `src/requests/cookies.py` lines 225–232

```py
    def iterkeys(self):
        """Dict-like iterkeys() that returns an iterator of names of cookies
        from the jar.

        .. seealso:: itervalues() and iteritems().
        """
        for cookie in iter(self):
            yield cookie.name
```

### `src/requests/cookies.py` lines 242–249

```py
    def itervalues(self):
        """Dict-like itervalues() that returns an iterator of values of cookies
        from the jar.

        .. seealso:: iterkeys() and iteritems().
        """
        for cookie in iter(self):
            yield cookie.value
```

## dup_0 — approximate, 7 lines, 2 instances

### `src/requests/auth.py` lines 83–89

```py
    def __eq__(self, other):
        return all(
            [
                self.username == getattr(other, "username", None),
                self.password == getattr(other, "password", None),
            ]
        )
```

### `src/requests/auth.py` lines 305–311

```py
    def __eq__(self, other):
        return all(
            [
                self.username == getattr(other, "username", None),
                self.password == getattr(other, "password", None),
            ]
        )
```

## dup_2 — approximate, 7 lines, 3 instances

### `src/requests/cookies.py` lines 234–240

```py
    def keys(self):
        """Dict-like keys() that returns a list of names of cookies from the
        jar.

        .. seealso:: values() and items().
        """
        return list(self.iterkeys())
```

### `src/requests/cookies.py` lines 251–257

```py
    def values(self):
        """Dict-like values() that returns a list of values of cookies from the
        jar.

        .. seealso:: keys() and items().
        """
        return list(self.itervalues())
```

### `src/requests/cookies.py` lines 268–275

```py
    def items(self):
        """Dict-like items() that returns a list of name-value tuples from the
        jar. Allows client-code to call ``dict(RequestsCookieJar)`` and get a
        vanilla python dict of key value pairs.

        .. seealso:: keys() and values().
        """
        return list(self.iteritems())
```

## dup_3 — approximate, 7 lines, 2 instances

### `src/requests/cookies.py` lines 277–283

```py
    def list_domains(self):
        """Utility method to list all the domains in the jar."""
        domains = []
        for cookie in iter(self):
            if cookie.domain not in domains:
                domains.append(cookie.domain)
        return domains
```

### `src/requests/cookies.py` lines 285–291

```py
    def list_paths(self):
        """Utility method to list all the paths in the jar."""
        paths = []
        for cookie in iter(self):
            if cookie.path not in paths:
                paths.append(cookie.path)
        return paths
```

## dup_5 — approximate, 6 lines, 3 instances

### `tests/test_requests.py` lines 269–274

```py
    def test_http_301_changes_post_to_get(self, httpbin):
        r = requests.post(httpbin("status", "301"))
        assert r.status_code == 200
        assert r.request.method == "GET"
        assert r.history[0].status_code == 301
        assert r.history[0].is_redirect
```

### `tests/test_requests.py` lines 284–289

```py
    def test_http_302_changes_post_to_get(self, httpbin):
        r = requests.post(httpbin("status", "302"))
        assert r.status_code == 200
        assert r.request.method == "GET"
        assert r.history[0].status_code == 302
        assert r.history[0].is_redirect
```

### `tests/test_requests.py` lines 298–303

```py
    def test_http_303_changes_post_to_get(self, httpbin):
        r = requests.post(httpbin("status", "303"))
        assert r.status_code == 200
        assert r.request.method == "GET"
        assert r.history[0].status_code == 303
        assert r.history[0].is_redirect
```

## dup_6 — approximate, 6 lines, 2 instances

### `tests/test_requests.py` lines 291–296

```py
    def test_http_302_doesnt_change_head_to_get(self, httpbin):
        r = requests.head(httpbin("status", "302"), allow_redirects=True)
        assert r.status_code == 200
        assert r.request.method == "HEAD"
        assert r.history[0].status_code == 302
        assert r.history[0].is_redirect
```

### `tests/test_requests.py` lines 305–310

```py
    def test_http_303_doesnt_change_head_to_get(self, httpbin):
        r = requests.head(httpbin("status", "303"), allow_redirects=True)
        assert r.status_code == 200
        assert r.request.method == "HEAD"
        assert r.history[0].status_code == 303
        assert r.history[0].is_redirect
```

## dup_8 — approximate, 6 lines, 2 instances

### `tests/test_requests.py` lines 1801–1806

```py
    def test_header_no_return_chars(self, httpbin, invalid_header):
        """Ensure that a header containing return character sequences raise an
        exception. Otherwise, multiple headers are created from single string.
        """
        with pytest.raises(InvalidHeader):
            requests.get(httpbin("get"), headers=invalid_header)
```

### `tests/test_requests.py` lines 1820–1825

```py
    def test_header_no_leading_space(self, httpbin, invalid_header):
        """Ensure headers containing leading whitespace raise
        InvalidHeader Error before sending.
        """
        with pytest.raises(InvalidHeader):
            requests.get(httpbin("get"), headers=invalid_header)
```

## dup_9 — approximate, 5 lines, 2 instances

### `tests/test_requests.py` lines 1906–1910

```py
    def test_should_strip_auth_host_change(self):
        s = requests.Session()
        assert s.should_strip_auth(
            "http://example.com/foo", "http://another.example.com/"
        )
```

### `tests/test_requests.py` lines 1935–1939

```py
    def test_should_strip_auth_port_change(self):
        s = requests.Session()
        assert s.should_strip_auth(
            "http://example.com:1234/foo", "https://example.com:4321/bar"
        )
```
