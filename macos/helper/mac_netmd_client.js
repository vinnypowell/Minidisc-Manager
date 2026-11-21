'use strict';
// The standard-disc (NetMD) counterpart of mac_client.js: the app runs it where Windows runs netmd_helper.js
//     node mac_netmd_client.js <command> [json-args]
// and it asks the background service to run that command for a standard MiniDisc.
process.env.MDM_HELPER = 'netmd';
require('./mac_client.js');
