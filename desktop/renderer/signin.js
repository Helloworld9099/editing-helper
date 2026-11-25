(async () => {
  'use strict';
  const api = window.coach;
  const $ = (id) => document.getElementById(id);
  const request = $('request'), verify = $('verify'), account = $('account');
  const error = $('error'), status = $('status');
  let selectedEmail = '';
  let busy = false;

  function show(mode) {
    request.hidden = mode !== 'request';
    verify.hidden = mode !== 'verify';
    account.hidden = mode !== 'account';
  }
  function setBusy(value) {
    busy = value;
    for (const id of ['send-code', 'verify-code', 'sign-out', 'change-email']) {
      $(id).disabled = value;
    }
  }
  async function perform(fn) {
    if (busy) return;
    setBusy(true);
    error.textContent = '';
    status.textContent = '';
    try { return await fn(); }
    catch { error.textContent = 'Something went wrong. Please try again.'; }
    finally { setBusy(false); }
  }

  request.addEventListener('submit', (e) => {
    e.preventDefault();
    void perform(async () => {
      const email = $('email').value.trim();
      const res = await api.requestSignInCode(email);
      if (!res?.ok) { error.textContent = res?.message || 'Could not send a code.'; return; }
      selectedEmail = email;
      $('email-sent').textContent = 'Enter the code sent to ' + selectedEmail + '.';
      show('verify');
      $('code').focus();
    });
  });

  verify.addEventListener('submit', (e) => {
    e.preventDefault();
    void perform(async () => {
      const res = await api.verifySignInCode(selectedEmail, $('code').value.trim());
      if (!res?.ok) { error.textContent = res?.message || 'Verification failed.'; return; }
      status.textContent = 'Signed in. Closing this window…';
      show('account');
      $('signed-in-as').textContent = res.email || selectedEmail;
    });
  });

  $('change-email').addEventListener('click', () => {
    error.textContent = '';
    status.textContent = '';
    $('code').value = '';
    show('request');
    $('email').focus();
  });
  $('sign-out').addEventListener('click', () => {
    void perform(async () => {
      await api.signOut();
      show('request');
      status.textContent = 'Signed out.';
    });
  });
  let session;
  try { session = await api.authStatus(); } catch {}
  if (!session?.configured) {
    show('request');
    request.querySelector('button').disabled = true;
    error.textContent = 'This version has not been connected to a public service yet.';
    return;
  }
  if (session.signedIn) {
    show('account');
    $('signed-in-as').textContent = 'Signed in as ' + (session.email || 'your account');
  } else {
    show('request');
    $('email').focus();
  }
})();
