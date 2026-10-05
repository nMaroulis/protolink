import React from 'react';
import {Redirect, useLocation} from '@docusaurus/router';
import useBaseUrl from '@docusaurus/useBaseUrl';

export default function DurableExecutionRedirect() {
  const target = useBaseUrl('/docs/execution-tools/');
  const {hash} = useLocation();
  return <Redirect to={target + (hash || '#durable-execution')} />;
}
