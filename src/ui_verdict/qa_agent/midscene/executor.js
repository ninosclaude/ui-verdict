/**
 * QA-Agent Midscene Executor
 * 
 * Node.js process that receives commands from Python via stdin,
 * executes them using Midscene.js/Playwright, and returns results via stdout.
 * 
 * Communication Protocol:
 * - Input: JSON objects, one per line
 * - Output: JSON objects, one per line
 * 
 * Commands:
 * - launch: Open browser and navigate to URL
 * - screenshot: Take screenshot
 * - aiAction: Execute natural language action via Midscene
 * - keyboard: Press keyboard keys
 * - type: Type text
 * - goto: Navigate to URL
 * - close: Close browser
 */

import { chromium, firefox, webkit } from 'playwright';
import readline from 'readline';

// Browser instance
let browser = null;
let page = null;

// Response helper
function respond(data) {
    console.log(JSON.stringify(data));
}

// Command handlers
const handlers = {
    async launch({ url, config = {} }) {
        try {
            const browserType = config.browser === 'firefox' ? firefox 
                              : config.browser === 'webkit' ? webkit 
                              : chromium;
            
            browser = await browserType.launch({
                headless: config.headless ?? true,
            });
            
            page = await browser.newPage({
                viewport: config.viewport || { width: 1920, height: 1080 },
            });
            
            await page.goto(url, { waitUntil: 'networkidle' });
            
            respond({ success: true, url });
        } catch (error) {
            respond({ success: false, error: error.message });
        }
    },

    async screenshot({ path }) {
        try {
            if (!page) throw new Error('No page open');
            await page.screenshot({ path, fullPage: false });
            respond({ success: true, path });
        } catch (error) {
            respond({ success: false, error: error.message });
        }
    },

    async aiAction({ instruction }) {
        try {
            if (!page) throw new Error('No page open');
            
            // TODO: Integrate Midscene.js aiAction
            // For now, use simple Playwright locator
            // This will be replaced with actual Midscene integration
            
            // Parse simple click instructions
            const clickMatch = instruction.match(/click on ['"](.+)['"]/i);
            if (clickMatch) {
                const target = clickMatch[1];
                await page.getByText(target, { exact: false }).first().click();
                respond({ success: true, action: 'click', target });
                return;
            }
            
            // Parse simple type instructions
            const typeMatch = instruction.match(/type ['"](.+)['"]/i);
            if (typeMatch) {
                const text = typeMatch[1];
                await page.keyboard.type(text);
                respond({ success: true, action: 'type', text });
                return;
            }
            
            respond({ success: false, error: `Unknown instruction: ${instruction}` });
        } catch (error) {
            respond({ success: false, error: error.message });
        }
    },

    async keyboard({ keys }) {
        try {
            if (!page) throw new Error('No page open');
            
            // Parse key combination (e.g., "ctrl+o" -> Control+o)
            const keyMap = {
                'ctrl': 'Control',
                'alt': 'Alt',
                'shift': 'Shift',
                'meta': 'Meta',
                'cmd': 'Meta',
            };
            
            const parts = keys.toLowerCase().split('+');
            const modifiers = [];
            let key = '';
            
            for (const part of parts) {
                if (keyMap[part]) {
                    modifiers.push(keyMap[part]);
                } else {
                    key = part.length === 1 ? part : part.charAt(0).toUpperCase() + part.slice(1);
                }
            }
            
            const combo = [...modifiers, key].join('+');
            await page.keyboard.press(combo);
            
            respond({ success: true, keys: combo });
        } catch (error) {
            respond({ success: false, error: error.message });
        }
    },

    async type({ text }) {
        try {
            if (!page) throw new Error('No page open');
            await page.keyboard.type(text);
            respond({ success: true, text });
        } catch (error) {
            respond({ success: false, error: error.message });
        }
    },

    async goto({ url }) {
        try {
            if (!page) throw new Error('No page open');
            await page.goto(url, { waitUntil: 'networkidle' });
            respond({ success: true, url });
        } catch (error) {
            respond({ success: false, error: error.message });
        }
    },

    async close() {
        try {
            if (browser) {
                await browser.close();
                browser = null;
                page = null;
            }
            respond({ success: true });
        } catch (error) {
            respond({ success: false, error: error.message });
        }
    },
};

// Main loop - read commands from stdin
const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: false,
});

rl.on('line', async (line) => {
    try {
        const command = JSON.parse(line);
        const handler = handlers[command.action];
        
        if (!handler) {
            respond({ success: false, error: `Unknown action: ${command.action}` });
            return;
        }
        
        await handler(command);
    } catch (error) {
        respond({ success: false, error: error.message });
    }
});

// Handle process termination
process.on('SIGTERM', async () => {
    if (browser) await browser.close();
    process.exit(0);
});

process.on('SIGINT', async () => {
    if (browser) await browser.close();
    process.exit(0);
});

// Signal ready
respond({ ready: true, version: '1.0.0' });
