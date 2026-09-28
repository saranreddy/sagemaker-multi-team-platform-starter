"""Architecture diagram for saranreddy/sagemaker-multi-team-platform-starter.

Verified against main @ 68d7704. Every node maps to main.tf, modules/{team,reaper-lambda,
endpoint-alarm-lambda}/*.tf or the Lambda sources under modules/*/src/.

Render:  pip install diagrams   (also needs Graphviz: apt install graphviz / brew install graphviz)
         python docs/architecture.py   ->  docs/architecture.png (written next to this script)
"""
import os

from diagrams import Cluster, Diagram, Edge, getdiagram
from diagrams.aws.compute import ECR, LambdaFunction
from diagrams.aws.cost import Budgets
from diagrams.aws.general import User, Users
from diagrams.aws.integration import EventbridgeRule, SNS
from diagrams.aws.management import CloudwatchAlarm
from diagrams.aws.ml import Sagemaker, SagemakerModel, SagemakerNotebook
from diagrams.aws.security import IAMRole
from diagrams.aws.storage import SimpleStorageServiceS3Bucket
from diagrams.onprem.iac import Terraform

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "architecture")  # -> architecture.png next to this script

FONT = "DejaVu Sans"
GRAPH = {
    "fontname": FONT, "fontsize": "34", "labelloc": "t", "pad": "0.4",
    "nodesep": "0.4", "ranksep": "1.0", "splines": "spline", "newrank": "true",
    "compound": "true",
}
NODE = {"fontname": FONT, "fontsize": "21", "imagepos": "tc"}
EDGE = {"fontname": FONT, "fontsize": "19", "color": "#555555",
        # enter/leave icons at mid-height so arrowheads never land on label text
        "tailport": "e", "headport": "w"}

# diagrams.Edge hard-codes a 13pt label font on every edge; raise it so edge labels stay
# readable when the PNG is scaled down to README width.
Edge._default_edge_attrs = {"fontcolor": "#2D3436", "fontname": FONT, "fontsize": "19"}


def box(bg, pen, style="rounded"):
    return {"bgcolor": bg, "pencolor": pen, "fontname": FONT, "fontsize": "21",
            "style": style, "labeljust": "l", "margin": "24"}


TF_BOX = box("#fff4e0", "#e66100")                  # deployed by Terraform
SUB_BOX = box("#fffaf2", "#e66100")                 # sub-group inside a Terraform box
RUN_BOX = box("#e8f1fb", "#1a5fb4")                 # created by scripts / CLI
EXEC_BOX = box("#f3eefa", "#613583")                # per execution / runtime
MANAGED_BOX = box("#f6f5f4", "#9a9996", "dashed")   # not created by this repo
ACCOUNT_BOX = box("#ffffff", "#232f3e")

FLOW = dict(color="#1a5fb4", fontcolor="#1a5fb4", penwidth="2.2")
IO = dict(color="#26a269", fontcolor="#1e7d4f", penwidth="1.8")
IAM = dict(color="#c01c28", fontcolor="#c01c28", style="dashed", penwidth="1.6", constraint="false")
AUX = dict(color="#8a8a8a", fontcolor="#5e5c64", style="dotted", penwidth="1.8")
SETUP = dict(color="#e66100", fontcolor="#c64600", style="dashed", penwidth="1.8")
MANUAL = dict(color="#26a269", fontcolor="#1e7d4f", style="dashed", penwidth="2.2")
FAIL = dict(color="#c01c28", fontcolor="#c01c28", penwidth="2.2")
OPT = dict(color="#b5835a", fontcolor="#8f5f3a", style="dashed", penwidth="1.8")
HIDDEN = dict(style="invis")
DOWN = dict(tailport="s", headport="n")
UP = dict(tailport="n", headport="s")


def same_rank(*nodes):
    getdiagram().dot.body.append("{rank=same; " + " ".join(f'"{n._id}";' for n in nodes) + "}")


# Top-to-bottom layout: row 1 is the team sign-in path, row 2 the per-team resources,
# rows 3-4 the platform guardrails. Keeps the PNG narrow enough for README width.
GRAPH["pad"] = "0.7"
GRAPH["nodesep"] = "1.3"
GRAPH["ranksep"] = "0.9"
GRAPH["forcelabels"] = "true"
EDGE_TB = {k: v for k, v in EDGE.items() if k not in ("tailport", "headport")}
ROW = dict(tailport="e", headport="w")     # flat edge inside a row, left -> right

with Diagram(
    "sagemaker-multi-team-platform-starter",
    filename=OUT, outformat="png", show=False, direction="TB",
    graph_attr=GRAPH, node_attr=NODE, edge_attr=EDGE_TB,
):
    ds = Users("Team data\nscientists")
    eng = User("Platform\nengineer")
    tf = Terraform("terraform apply\n(teams map)")

    with Cluster("AWS account  (Studio in default VPC unless vpc_id is set)", graph_attr=ACCOUNT_BOX):
        with Cluster("Created at runtime", graph_attr=EXEC_BOX):
            ep = Sagemaker("Team endpoints,\njobs, Studio apps\n(Team tag)")

        with Cluster("Terraform: guardrails  (platform-wide)", graph_attr=TF_BOX):
            rule = EventbridgeRule("Rule: endpoint\nstate change\n(InService)")
            alarmfn = LambdaFunction("Alarm Lambda")
            reaper = LambdaFunction("Reaper Lambda\n(report-only\nby default)")
            cron = EventbridgeRule("Rule: daily\ncron 02:00 UTC")
            psns = SNS("Platform SNS\n+ email subs")

        with Cluster("Created by Alarm Lambda", graph_attr=EXEC_BOX):
            alarms = CloudwatchAlarm("Alarms: 5XX,\np90 latency,\ninvocation drop")

        with Cluster("Terraform: per team  (for_each var.teams)", graph_attr=TF_BOX) as team:
            # (declaration order tuned so graphviz keeps each row left-to-right)
            prof = SagemakerNotebook("User profiles\n<team>-\n<member>")
            reg = SagemakerModel("Model package\ngroup <project>-\n<team>-registry")
            s3 = SimpleStorageServiceS3Bucket("Bucket\n<project>-\n<team>-data-\n<acct>")
            ecr = ECR("ECR repo\n<project>/\n<team>/\nmodels")
            budget = Budgets("Budget, tag\nuser:Team\n80/100% actual,\n90% forecast")
            role = IAMRole("Team execution\nrole: Team-tag\nABAC, instance\nallowlist")
            tsns = SNS("Team SNS\n+ email subs")

        with Cluster("Terraform: shared Studio", graph_attr=TF_BOX):
            domain = Sagemaker("Studio domain\nIAM auth, public\ninternet (VpcOnly\noptional)")
            sdrole = IAMRole("Studio default\nrole (minimal\nfallback)")

    # setup
    eng >> Edge(xlabel="apply", **ROW, **SETUP) >> tf
    tf >> Edge(label="creates", lhead=team.name, **SETUP) >> prof

    # row 1: sign-in path
    ds >> Edge(xlabel="sign in", **ROW, **FLOW) >> domain
    domain >> Edge(**ROW, **FLOW) >> prof
    prof >> Edge(xlabel="runs as", **ROW, **FLOW) >> role
    same_rank(ds, domain, prof, role)

    # row 2: team resources
    domain >> Edge(label="default role", **AUX) >> sdrole
    role >> Edge(label="own team only", tailport="s", **IO) >> ecr
    role >> Edge(tailport="s", **IO) >> reg
    role >> Edge(tailport="s", **IO) >> s3
    budget >> Edge(xlabel="alert", **ROW, **AUX) >> tsns
    same_rank(sdrole, ecr, reg, s3, budget, tsns)

    # row 3: endpoint alarms
    role >> Edge(label="create", tailport="s", **FLOW) >> ep
    ep >> Edge(xlabel="event", **ROW, **FLOW) >> rule
    rule >> Edge(**ROW, **FLOW) >> alarmfn
    alarmfn >> Edge(xlabel="put", **ROW, **FLOW) >> alarms
    alarms >> Edge(label="notify", tailport="n", headport="s", constraint="false", **FLOW) >> tsns
    alarmfn >> Edge(label="untagged", **AUX) >> psns
    same_rank(ep, rule, alarmfn, alarms)
    # vertical pins so each row keeps its left-to-right order across clusters
    s3 >> Edge(**HIDDEN) >> rule
    budget >> Edge(**HIDDEN) >> alarmfn
    tsns >> Edge(**HIDDEN) >> alarms
    rule >> Edge(**HIDDEN) >> reaper
    alarmfn >> Edge(**HIDDEN) >> psns

    # row 4: idle-resource reaper
    ep >> Edge(**HIDDEN) >> cron
    cron >> Edge(**ROW, **FLOW) >> reaper
    ep << Edge(label="scan: 7d no calls,\napps idle 24h", **AUX) << reaper
    ep << Edge(label="delete if\nreaper_enabled", **OPT) << reaper
    reaper >> Edge(label="report", tailport="n", headport="s", constraint="false", **AUX) >> tsns
    reaper >> Edge(xlabel="errors,\nunknown\nteam", **ROW, **AUX) >> psns
    same_rank(cron, reaper, psns)
