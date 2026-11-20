import { describe, expect, it } from 'vitest';
import { esc, href } from './html.js';

describe('esc', () => {
  it('closes the ways out of an attribute or a text node', () => {
    expect(esc('<img src=x onerror="alert(1)">')).toBe('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
    expect(esc('Tom & Jerry')).toBe('Tom &amp; Jerry');
  });
  it('null and undefined are empty, not the words', () => {
    expect(esc(null)).toBe('');
    expect(esc(undefined)).toBe('');
  });
});

describe('href', () => {
  it('passes the urls the data files actually hold', () => {
    expect(href('https://www.magicbricks.com/propertyDetails/x-1234')).toBe('https://www.magicbricks.com/propertyDetails/x-1234');
    expect(href('http://example.com/a?b=1&c=2')).toBe('http://example.com/a?b=1&amp;c=2');
  });
  it('drops a scheme that would run as code in our origin', () => {
    expect(href('javascript:alert(1)')).toBe('');
    expect(href('JavaScript:alert(1)')).toBe('');
    expect(href('data:text/html,<script>alert(1)</script>')).toBe('');
    // the browser strips tabs and newlines inside a url before following it, so a scheme test has to
    // run on the parsed url and not on the raw string
    expect(href('java\nscript:alert(1)')).toBe('');
    expect(href('\t javascript:alert(1)')).toBe('');
  });
  it('drops what it cannot parse, and never throws', () => {
    expect(href('/data/gurgaon.json')).toBe('');
    expect(href('')).toBe('');
    expect(href(null)).toBe('');
    expect(href(undefined)).toBe('');
    expect(href({})).toBe('');
  });
});
