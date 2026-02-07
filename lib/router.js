const axios = require('axios');
const path = require('path');
const { spawn } = require('child_process');

const OLLAMA_API = 'http://localhost:11434/api/generate';
const AGENTS_DIR = path.join(__dirname, 'agents');

async function runOllama(model, prompt) {
  const response = await axios.post(OLLAMA_API, {
    model,
    prompt,
    stream: false,
    options: { temperature: 0.1 }
  });
  return response.data.response.trim();
}

async function runAgent(agent, params) {
  return new Promise((resolve) => {
    const file = `${agent}-agent.js`;
    const proc = spawn('node', [path.join(AGENTS_DIR, file)]);
    let output = '';
    proc.stdout.on('data', d => output += d.toString());
    proc.stdin.write(JSON.stringify(params));
    proc.stdin.end();
    proc.on('close', () => {
      const json = output.split('\n').find(l => l.trim().startsWith('{'));
      resolve(json ? json.trim() : output.trim());
    });
  });
}

async function meridQuery(query) {
  console.log(`\nQuery: ${query}\n`);
  const strategist = await runOllama('merid-strategist', query);
  console.log('Strategist → ' + strategist);

  let finalInput = strategist;

  try {
    const route = JSON.parse(strategist);
    if (route.route === 'agent_required') {
      console.log(`Running ${route.agent} agent...`);
      const agentOut = await runAgent(route.agent, route.params);
      console.log('Agent → ' + agentOut);
      finalInput = agentOut;
    } else if (route.response) {
      finalInput = route.response;
    }
  } catch {}

  const final = await runOllama('merid-interface', finalInput);
  console.log('\nFINAL ANSWER:');
  console.log(final + '\n');
}

const q = process.argv.slice(2).join(' ');
if (q) meridQuery(q);
else console.log('Usage: node router.js "query"');
