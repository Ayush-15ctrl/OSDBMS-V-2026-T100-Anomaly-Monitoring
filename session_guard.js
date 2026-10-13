/** OS/DBMS concept: client heartbeat and crash/reconnect signaling. */

/**
 * Register immediate page lifecycle delivery for a server-owned exam session.
 * @param {object} options
 * @param {string} options.endpoint Event endpoint.
 * @param {string} options.sessionToken Server-side session token.
 * @param {number} options.heartbeatSeconds Heartbeat interval.
 * @returns {() => void} Cleanup function for listeners and heartbeat.
 */
export function installSessionGuard(options) {}

/**
 * Send one event immediately without client-side buffering.
 * @param {string} endpoint Event endpoint.
 * @param {object} event Behavior event payload.
 * @returns {Promise<Response>} Server response promise.
 */
export function postImmediateEvent(endpoint, event) {}