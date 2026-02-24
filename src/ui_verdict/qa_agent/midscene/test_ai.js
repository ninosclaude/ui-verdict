/**
 * Test Midscene AI capabilities
 */

import { spawn } from 'child_process';
import readline from 'readline';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

function sendCommand(proc, command) {
    return new Promise((resolve, reject) => {
        const rl = readline.createInterface({ input: proc.stdout });
        
        const onLine = (line) => {
            if (!line.startsWith('{') && !line.startsWith('[')) {
                console.error('[log]', line);
                return;
            }
            rl.close();
            try {
                resolve(JSON.parse(line));
            } catch (e) {
                reject(new Error(`Parse error: ${line}`));
            }
        };
        
        rl.on('line', onLine);
        proc.stdin.write(JSON.stringify(command) + '\n');
    });
}

async function main() {
    console.log('Starting Midscene AI test...\n');
    
    const proc = spawn('node', ['executor.js'], {
        cwd: __dirname,
        stdio: ['pipe', 'pipe', 'inherit'],
    });
    
    // Wait for ready
    const readyRl = readline.createInterface({ input: proc.stdout });
    await new Promise((resolve) => {
        const handler = (line) => {
            if (line.startsWith('{')) {
                readyRl.close();
                resolve();
            }
        };
        readyRl.on('line', handler);
    });
    console.log('✅ Executor ready\n');
    
    // Launch browser with a form page
    console.log('--- Test: Open DuckDuckGo ---');
    const launch = await sendCommand(proc, {
        action: 'launch',
        url: 'https://duckduckgo.com',
        config: { headless: true },
    });
    console.log('Launch:', launch.success ? '✅' : '❌', launch.url || launch.error);
    
    // Take screenshot
    const ss1 = await sendCommand(proc, {
        action: 'screenshot',
        path: '/tmp/midscene_ai_test_1.png',
    });
    console.log('Screenshot 1:', ss1.success ? '✅' : '❌');
    
    // Test aiAction - type in search box
    console.log('\n--- Test: aiAction (type in search) ---');
    const aiAction = await sendCommand(proc, {
        action: 'aiAction',
        instruction: 'Click on the search input field and type "hello world"',
    });
    console.log('aiAction:', aiAction.success ? '✅' : '❌', aiAction.action || aiAction.error);
    
    // Take screenshot after action
    const ss2 = await sendCommand(proc, {
        action: 'screenshot',
        path: '/tmp/midscene_ai_test_2.png',
    });
    console.log('Screenshot 2:', ss2.success ? '✅' : '❌');
    
    // Test aiBoolean
    console.log('\n--- Test: aiBoolean ---');
    const aiBool = await sendCommand(proc, {
        action: 'aiBoolean',
        question: 'Is there a search input field visible on this page?',
    });
    console.log('aiBoolean:', aiBool.success ? '✅' : '❌', 'Result:', aiBool.result, aiBool.error || '');
    
    // Test aiQuery
    console.log('\n--- Test: aiQuery ---');
    const aiQuery = await sendCommand(proc, {
        action: 'aiQuery',
        query: 'What text is in the search input field?',
    });
    console.log('aiQuery:', aiQuery.success ? '✅' : '❌', 'Result:', aiQuery.result, aiQuery.error || '');
    
    // Close
    await sendCommand(proc, { action: 'close' });
    proc.kill();
    
    console.log('\n✅ All Midscene AI tests completed!');
}

main().catch(console.error);
