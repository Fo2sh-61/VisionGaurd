import { useNavigate } from 'react-router-dom';
import { TOOLS_LIST } from '@/services/mockData';

export function Tools() {
  const navigate = useNavigate();

  return (
    <div className="screen">
      <div className="screen__title">Tools</div>
      <p className="screen__lead">Seven tools. Each answers one question, with the footage right there.</p>

      <div className="stack">
        {TOOLS_LIST.map((tool) => (
          <button
            key={tool.id}
            type="button"
            className="card row row--pressable"
            style={{ padding: 16 }}
            onClick={() => navigate(`/tool/${tool.id}`, { state: { autoRun: true } })}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="row__name">{tool.title}</div>
              <div className="row__sub">{tool.blurb}</div>
            </div>
            <span className="row__chevron">›</span>
          </button>
        ))}
      </div>
    </div>
  );
}
