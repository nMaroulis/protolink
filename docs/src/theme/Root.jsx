import React, {useEffect, useState} from 'react';
import {useLocation} from '@docusaurus/router';

const GA_MEASUREMENT_ID = 'G-39EKFHFG47';
const CONSENT_KEY = 'protolink:analytics-consent';

function loadGoogleAnalytics() {
  if (typeof window === 'undefined' || window.__protolinkAnalyticsLoaded) {
    return;
  }

  window.__protolinkAnalyticsLoaded = true;
  window.dataLayer = window.dataLayer || [];
  window.gtag = window.gtag || function gtag() {
    window.dataLayer.push(arguments);
  };

  const script = document.createElement('script');
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`;
  document.head.appendChild(script);

  window.gtag('js', new Date());
}

function trackPageView(path) {
  loadGoogleAnalytics();
  window.gtag('config', GA_MEASUREMENT_ID, {page_path: path});
}

function readStoredConsent() {
  try {
    const value = window.localStorage.getItem(CONSENT_KEY);
    return value === 'accepted' || value === 'declined' ? value : null;
  } catch {
    return null;
  }
}

function writeStoredConsent(value) {
  try {
    window.localStorage.setItem(CONSENT_KEY, value);
  } catch {
    // If storage is unavailable, still respect the current in-memory choice.
  }
}

function AnalyticsConsentBanner({onAccept, onDecline}) {
  return (
    <aside className="analytics-consent" aria-label="Analytics consent">
      <span className="analytics-consent__icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" role="img">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a4.3 4.3 0 0 0 5 5 4.3 4.3 0 0 0 4.8 4.8Z" />
          <path d="M8.6 8.7h.01M7.8 14.6h.01M13.2 15.5h.01" />
        </svg>
      </span>
      <p>
        <strong>ProtoLink is open source.</strong> We use optional Google Analytics to understand docs usage.
        No ads or profiling. You can accept or decline; the site works perfectly either way.
      </p>
      <div className="analytics-consent__actions">
        <button className="analytics-consent__button analytics-consent__button--secondary" onClick={onDecline} type="button">
          Decline
        </button>
        <button className="analytics-consent__button analytics-consent__button--primary" onClick={onAccept} type="button">
          Accept
        </button>
      </div>
    </aside>
  );
}

export default function Root({children}) {
  const location = useLocation();
  const [consent, setConsent] = useState(undefined);

  useEffect(() => {
    setConsent(readStoredConsent());
  }, []);

  useEffect(() => {
    if (consent !== 'accepted') {
      return;
    }

    trackPageView(`${location.pathname}${location.search}${location.hash}`);
  }, [consent, location.hash, location.pathname, location.search]);

  function acceptAnalytics() {
    writeStoredConsent('accepted');
    setConsent('accepted');
  }

  function declineAnalytics() {
    writeStoredConsent('declined');
    setConsent('declined');
  }

  return (
    <>
      {children}
      {consent === null && (
        <AnalyticsConsentBanner onAccept={acceptAnalytics} onDecline={declineAnalytics} />
      )}
    </>
  );
}
